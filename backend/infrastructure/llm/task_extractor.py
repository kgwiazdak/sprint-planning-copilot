from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, MutableMapping, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, ModelResponse, dynamic_prompt, wrap_model_call
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, tool
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from pydantic import ValidationError

from backend.schemas import ExtractionResult, Task

logger = logging.getLogger(__name__)

try:  # pragma: no cover - compatibility for docs using these names
    from langchain.agents.middleware import StateContext, ThreadContext  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    class StateContext(TypedDict, total=False):
        messages: list[Any]

    class ThreadContext(TypedDict, total=False):
        role: str
        transcript: str
        transcript_chars: int
        transcript_lines: int
        valid_speakers: list[str]
        confidence_hint: float
        current_result_json: str

try:  # pragma: no cover
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover
    LANGGRAPH_AVAILABLE = False
    MemorySaver = None  # type: ignore[assignment]
    StateGraph = None  # type: ignore[assignment]
    START = "START"  # type: ignore[assignment]
    END = "END"  # type: ignore[assignment]


class ExtractionGraphState(TypedDict, total=False):
    transcript: str
    valid_speakers: list[str]
    planner_raw: str
    result: ExtractionResult
    confidence_report: dict[str, Any]
    timings: dict[str, float]


@dataclass
class TaskConfidence:
    summary: str
    overall: float
    speaker: float
    points: float
    rationale: str


def _extract_speakers_from_transcript(transcript: str) -> list[str]:
    pattern = re.compile(r"^([A-Z][^:]{1,50}):\s", re.MULTILINE)
    seen: set[str] = set()
    speakers: list[str] = []
    for name in pattern.findall(transcript):
        normalized = name.strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            speakers.append(normalized)
    return speakers


def _role_from_intro_filename(path: Path) -> str:
    stem = path.stem
    if stem.lower().startswith("intro_"):
        stem = stem[6:]
    stem = stem.replace("_", " ").strip()
    if not stem:
        return "Speaker"
    return " ".join(token.capitalize() for token in stem.split())


def _known_voice_names(intro_dir: str | Path | None = None, pattern: str | None = None) -> list[str]:
    directory = Path(intro_dir or os.getenv("INTRO_AUDIO_DIR", "data/voices"))
    glob_pattern = pattern or os.getenv("INTRO_AUDIO_PATTERN", "intro_*.*")
    if not directory.exists():
        return []
    seen: set[str] = set()
    names: list[str] = []
    for path in sorted(directory.glob(glob_pattern)):
        if not path.is_file():
            continue
        name = _role_from_intro_filename(path)
        key = name.lower()
        if key not in seen:
            seen.add(key)
            names.append(name)
    return names


def _augment_with_known_voices(extracted: list[str]) -> list[str]:
    known = _known_voice_names()
    if not known:
        return extracted
    seen: set[str] = set()
    out: list[str] = []
    for name in extracted + known:
        key = name.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(name.strip())
    return out


def _fuzzy_match_speaker(name: str, valid_speakers: list[str], threshold: float = 0.6) -> str | None:
    if not name or not valid_speakers:
        return None
    target = name.lower().strip()
    best_score = 0.0
    best_name: str | None = None
    for speaker in valid_speakers:
        candidate = speaker.lower().strip()
        if candidate == target:
            return speaker
        score = SequenceMatcher(None, target, candidate).ratio()
        if score > best_score:
            best_score = score
            best_name = speaker
    return best_name if best_score >= threshold else None


class LLMExtractor:
    def __init__(self) -> None:
        self.last_timings: dict[str, float] = {}
        self._provider = os.getenv("LLM_PROVIDER", "openai").lower()
        self._runtime = os.getenv("AGENT_RUNTIME", "langgraph").lower()
        self._confidence_threshold = float(os.getenv("AGENT_CONFIDENCE_THRESHOLD", "0.75"))
        self._max_low_conf_task_ratio = float(os.getenv("AGENT_MAX_LOW_CONF_TASK_RATIO", "0.5"))
        self._model_switch_char_threshold = int(os.getenv("AGENT_MODEL_SWITCH_CHAR_THRESHOLD", "12000"))
        self._model_switch_low_conf_threshold = float(os.getenv("AGENT_MODEL_SWITCH_LOW_CONF_THRESHOLD", "0.7"))
        self._planner_tools = self._build_planner_tools()
        self._agents = {"planner": self._build_role_agent("planner"), "critic": self._build_role_agent("critic")}
        self._checkpointer = MemorySaver() if LANGGRAPH_AVAILABLE and MemorySaver else None
        self._graph = self._build_graph() if self._runtime == "langgraph" else None

    def extract(self, transcript: str) -> ExtractionResult:
        if self._graph:
            thread_id = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:16]
            state = self._graph.invoke({"transcript": transcript}, config={"configurable": {"thread_id": thread_id}})
            report = state.get("confidence_report", {})
            timings = dict(state.get("timings", {}))
            timings["agentic_overall_confidence"] = float(report.get("overall_confidence", 0.0))
            timings["agentic_low_confidence_tasks"] = float(report.get("low_confidence_tasks", 0))
            self.last_timings = timings
            return state["result"]
        result, timings = self._run_sequential(transcript)
        self.last_timings = timings
        return result

    def _build_graph(self):
        if not LANGGRAPH_AVAILABLE or StateGraph is None:
            return None
        g = StateGraph(ExtractionGraphState)
        g.add_node("context_agent", self._node_context_agent)
        g.add_node("planner_agent", self._node_planner_agent)
        g.add_node("parser_agent", self._node_parser_agent)
        g.add_node("critic_agent", self._node_critic_agent)
        g.add_node("policy_standard", self._node_policy_standard)
        g.add_node("policy_low_confidence", self._node_policy_low_confidence)
        g.add_edge(START, "context_agent")
        g.add_edge("context_agent", "planner_agent")
        g.add_edge("planner_agent", "parser_agent")
        g.add_edge("parser_agent", "critic_agent")
        g.add_conditional_edges("critic_agent", self._route_after_critic, {"policy_standard": "policy_standard", "policy_low_confidence": "policy_low_confidence"})
        g.add_edge("policy_standard", END)
        g.add_edge("policy_low_confidence", END)
        return g.compile(checkpointer=self._checkpointer)

    def _run_sequential(self, transcript: str) -> tuple[ExtractionResult, dict[str, float]]:
        state: ExtractionGraphState = {"transcript": transcript}
        state.update(self._node_context_agent(state))
        state.update(self._node_planner_agent(state))
        state.update(self._node_parser_agent(state))
        state.update(self._node_critic_agent(state))
        state.update(self._node_policy_low_confidence(state) if self._route_after_critic(state) == "policy_low_confidence" else self._node_policy_standard(state))
        return state["result"], state.get("timings", {})

    def _build_planner_tools(self) -> list[BaseTool]:
        @tool("normalize_issue_type", return_direct=False)
        def normalize_issue_type(issue_type: str) -> str:
            """Normalize arbitrary issue type text into Jira canonical type."""
            raw = (issue_type or "").strip().lower()
            if raw.startswith("story"):
                return "Story"
            if raw.startswith("bug"):
                return "Bug"
            if raw.startswith("spike"):
                return "Spike"
            return "Task"

        @tool("normalize_priority", return_direct=False)
        def normalize_priority(priority: str) -> str:
            """Normalize arbitrary priority text into Jira canonical priority."""
            raw = (priority or "").strip().lower()
            if raw.startswith("high") or raw.startswith("urgent") or raw.startswith("critical"):
                return "High"
            if raw.startswith("low"):
                return "Low"
            return "Medium"

        return [normalize_issue_type, normalize_priority]

    def _select_tools_for_role(self, role: str, context: ThreadContext) -> list[BaseTool]:
        if role != "planner":
            return []
        return self._planner_tools if int(context.get("transcript_chars", 0)) >= 2000 else []

    def _route_model(self, *, role: str, transcript: str, confidence_hint: float | None) -> tuple[str, str, float]:
        base = {"planner": os.getenv("AGENT_PLANNER_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")), "critic": os.getenv("AGENT_CRITIC_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")), "repair": os.getenv("AGENT_CRITIC_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))}
        strong = {"planner": os.getenv("AGENT_PLANNER_MODEL_STRONG", "gpt-4.1"), "critic": os.getenv("AGENT_CRITIC_MODEL_STRONG", "gpt-4.1"), "repair": os.getenv("AGENT_CRITIC_MODEL_STRONG", "gpt-4.1")}
        model_name = base.get(role, os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
        if len(transcript) > self._model_switch_char_threshold or (confidence_hint is not None and confidence_hint < self._model_switch_low_conf_threshold):
            model_name = strong.get(role, model_name)
        provider = self._provider
        if provider == "openai" and not os.getenv("OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_DEPLOYMENT") and os.getenv("AZURE_OPENAI_ENDPOINT"):
            provider = "azure"
        temp = 0.1 if role == "planner" else 0.0
        return provider, model_name, temp

    def _build_dynamic_prompt(self, *, role: str, context: ThreadContext) -> str:
        transcript = str(context.get("transcript", ""))
        speakers = context.get("valid_speakers") or []
        speakers_hint = ", ".join(speakers) if speakers else "none"
        if role == "planner":
            constraint = f'Allowed assignees: {speakers_hint}. assignee_name must match or be null.'
            return (
                "You are PlannerAgent. Return strict JSON with schema {tasks:[{summary,description,issue_type,assignee_name,priority,story_points,labels,links,quotes}]}. "
                "story_points must be integer. Use evidence quotes. "
                f"{constraint}\nTranscript:\n{transcript}"
            )
        return (
            "You are CriticAgent. Return strict JSON {overall_confidence,tasks:[{summary,overall,speaker,points,rationale}]}. "
            f"Known speakers: {speakers_hint}\nTasks JSON:\n{context.get('current_result_json','{}')}\nTranscript:\n{transcript[:8000]}"
        )

    def _build_llm_client(self, *, provider: str, model_name: str, temperature: float):
        if provider == "azure":
            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            if deployment and endpoint:
                return AzureChatOpenAI(
                    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                    azure_deployment=deployment,
                    azure_endpoint=endpoint,
                    temperature=temperature,
                )
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=os.getenv("OPENAI_API_KEY", "test-key"),
        )

    def _build_llm(self, role: str, *, transcript: str = "", confidence_hint: float | None = None):
        provider, model, temp = self._route_model(role=role, transcript=transcript, confidence_hint=confidence_hint)
        return self._build_llm_client(provider=provider, model_name=model, temperature=temp)

    def _build_role_agent(self, role: str):
        provider, model, temp = self._route_model(role=role, transcript="", confidence_hint=None)
        default_model = self._build_llm_client(provider=provider, model_name=model, temperature=temp)
        default_tools = self._planner_tools if role == "planner" else []

        @dynamic_prompt
        def role_prompt(request: ModelRequest[ThreadContext]) -> str:
            raw = request.runtime.context
            context: ThreadContext = dict(raw) if isinstance(raw, Mapping) else {}
            return self._build_dynamic_prompt(role=role, context=context)

        @wrap_model_call
        def route_and_track(request: ModelRequest[ThreadContext], handler) -> ModelResponse:
            raw = request.runtime.context
            context: ThreadContext = dict(raw) if isinstance(raw, Mapping) else {}
            transcript = str(context.get("transcript", ""))
            hint_raw = context.get("confidence_hint")
            hint = float(hint_raw) if isinstance(hint_raw, (float, int)) else None
            p, m, t = self._route_model(role=role, transcript=transcript, confidence_hint=hint)
            selected_model = self._build_llm_client(provider=p, model_name=m, temperature=t)
            selected_tools = self._select_tools_for_role(role, context)
            started = time.perf_counter()
            response = handler(request.override(model=selected_model, tools=selected_tools))
            elapsed = (time.perf_counter() - started) * 1000
            out_messages = []
            for msg in response.result:
                if isinstance(msg, AIMessage):
                    meta = dict(msg.additional_kwargs or {})
                    meta["agentic_model_call"] = {"role": role, "provider": p, "model_name": m, "temperature": t, "latency_ms": elapsed, "tools_count": len(selected_tools)}
                    msg = msg.model_copy(update={"additional_kwargs": meta})
                out_messages.append(msg)
            return ModelResponse(result=out_messages, structured_response=response.structured_response)

        return create_agent(model=default_model, tools=default_tools, middleware=[role_prompt, route_and_track])

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, Mapping) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "".join(parts)
        return str(content or "")

    def _invoke_role_agent(self, *, role: str, transcript: str, valid_speakers: list[str], current_result: ExtractionResult | None = None, confidence_hint: float | None = None) -> tuple[str, dict[str, float]]:
        context: ThreadContext = {
            "role": role,
            "transcript": transcript,
            "transcript_chars": len(transcript),
            "transcript_lines": len([line for line in transcript.splitlines() if line.strip()]),
            "valid_speakers": valid_speakers,
            "confidence_hint": float(confidence_hint) if confidence_hint is not None else 1.0,
            "current_result_json": json.dumps(current_result.model_dump() if current_result else {}, ensure_ascii=True),
        }
        user_msg = "Run planner and return only JSON." if role == "planner" else "Run critic and return only JSON."
        thread_id = hashlib.sha256(f"{role}:{transcript}".encode("utf-8")).hexdigest()[:16]
        out = self._agents[role].invoke({"messages": [{"role": "user", "content": user_msg}]}, context=context, config={"configurable": {"thread_id": thread_id}})
        timings: dict[str, float] = {}
        content = ""
        for msg in reversed(out.get("messages", [])):
            if not isinstance(msg, AIMessage):
                continue
            content = self._message_content_to_text(msg.content)
            call_meta = (msg.additional_kwargs or {}).get("agentic_model_call", {})
            if isinstance(call_meta, Mapping):
                if isinstance(call_meta.get("latency_ms"), (int, float)):
                    timings[f"latency_ms_{role}"] = float(call_meta["latency_ms"])
                if isinstance(call_meta.get("tools_count"), (int, float)):
                    timings[f"{role}_tools_count"] = float(call_meta["tools_count"])
            break
        return content, timings

    def _node_context_agent(self, state: ExtractionGraphState) -> dict[str, Any]:
        return {"valid_speakers": _augment_with_known_voices(_extract_speakers_from_transcript(state["transcript"]))}

    def _node_planner_agent(self, state: ExtractionGraphState) -> dict[str, Any]:
        raw, timings = self._invoke_role_agent(role="planner", transcript=state["transcript"], valid_speakers=state.get("valid_speakers", []))
        merged = dict(state.get("timings", {}))
        merged.update(timings)
        return {"planner_raw": raw, "timings": merged}

    def _node_parser_agent(self, state: ExtractionGraphState) -> dict[str, Any]:
        llm = self._build_llm("repair", transcript=state.get("transcript", ""))
        result = LLMExtractor._parse_or_repair_response(llm, state.get("planner_raw", ""))
        return {"result": LLMExtractor._validate_assignees(result, state.get("valid_speakers", []))}

    def _node_critic_agent(self, state: ExtractionGraphState) -> dict[str, Any]:
        transcript = state["transcript"]
        result = state["result"]
        speakers = state.get("valid_speakers", [])
        started = time.perf_counter()
        report = self._heuristic_confidence_report(transcript, result, speakers)
        try:
            raw, timings_from_model = self._invoke_role_agent(role="critic", transcript=transcript, valid_speakers=speakers, current_result=result, confidence_hint=float(report.get("overall_confidence", 1.0)))
            parsed = self._parse_critic_report(raw, result)
            if parsed:
                report = parsed
            merged = dict(state.get("timings", {}))
            merged.update(timings_from_model)
            state["timings"] = merged
        except Exception:
            logger.debug("Critic agent fallback to heuristic confidence report.", exc_info=True)
        timings = dict(state.get("timings", {}))
        timings["latency_ms_critic"] = (time.perf_counter() - started) * 1000
        return {"confidence_report": report, "timings": timings}

    def _node_policy_standard(self, state: ExtractionGraphState) -> dict[str, Any]:
        return {"result": self._apply_confidence_policy(result=state["result"], report=state.get("confidence_report", {}), force_human_review=False)}

    def _node_policy_low_confidence(self, state: ExtractionGraphState) -> dict[str, Any]:
        return {"result": self._apply_confidence_policy(result=state["result"], report=state.get("confidence_report", {}), force_human_review=True)}

    def _route_after_critic(self, state: ExtractionGraphState) -> str:
        report = state.get("confidence_report", {})
        overall = float(report.get("overall_confidence", 0.0))
        low_conf = int(report.get("low_confidence_tasks", 0))
        total = max(1, len(state["result"].tasks))
        if overall < self._confidence_threshold or (low_conf / total) >= self._max_low_conf_task_ratio:
            return "policy_low_confidence"
        return "policy_standard"

    @staticmethod
    def _parse_critic_report(raw: str, result: ExtractionResult) -> dict[str, Any] | None:
        data = json.loads(raw)
        items = data.get("tasks")
        if not isinstance(items, list):
            return None
        mapped: dict[str, TaskConfidence] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue
            summary = str(item.get("summary", "")).strip()
            if not summary:
                continue
            mapped[summary] = TaskConfidence(summary=summary, overall=float(item.get("overall", 0.0)), speaker=float(item.get("speaker", 0.0)), points=float(item.get("points", 0.0)), rationale=str(item.get("rationale", "")).strip())
        normalized: list[dict[str, Any]] = []
        low = 0
        for task in result.tasks:
            row = mapped.get(task.summary) or TaskConfidence(task.summary, 0.6, 0.6, 0.6, "critic_default")
            normalized.append({"summary": row.summary, "overall": max(0.0, min(1.0, row.overall)), "speaker": max(0.0, min(1.0, row.speaker)), "points": max(0.0, min(1.0, row.points)), "rationale": row.rationale})
            if row.overall < 0.75:
                low += 1
        overall = float(data.get("overall_confidence", 0.0))
        if overall <= 0:
            overall = sum(i["overall"] for i in normalized) / max(1, len(normalized))
        return {"overall_confidence": max(0.0, min(1.0, overall)), "tasks": normalized, "low_confidence_tasks": low}

    def _heuristic_confidence_report(self, transcript: str, result: ExtractionResult, valid_speakers: list[str]) -> dict[str, Any]:
        t_low = transcript.lower()
        rows: list[dict[str, Any]] = []
        low = 0
        for task in result.tasks:
            speaker = 0.95 if task.assignee_name and _fuzzy_match_speaker(task.assignee_name, valid_speakers, threshold=0.75) else (0.5 if valid_speakers else 1.0)
            points = 0.95 if task.story_points is not None else 0.4
            if task.story_points is not None and not re.search(r"\b(point|points|sp|story points?)\b", t_low):
                points = 0.6
            quote = 0.85 if task.quotes else 0.55
            overall = round((speaker * 0.45) + (points * 0.35) + (quote * 0.2), 3)
            if overall < self._confidence_threshold:
                low += 1
            rows.append({"summary": task.summary, "overall": overall, "speaker": round(speaker, 3), "points": round(points, 3), "rationale": "heuristic"})
        all_overall = round(sum(r["overall"] for r in rows) / max(1, len(rows)), 3)
        return {"overall_confidence": all_overall, "tasks": rows, "low_confidence_tasks": low}

    def _apply_confidence_policy(self, *, result: ExtractionResult, report: Mapping[str, Any], force_human_review: bool) -> ExtractionResult:
        by_summary = {
            str(item.get("summary", "")).strip(): item
            for item in (report.get("tasks") if isinstance(report.get("tasks"), list) else [])
            if isinstance(item, Mapping) and str(item.get("summary", "")).strip()
        }
        for task in result.tasks:
            row = by_summary.get(task.summary, {})
            overall = float(row.get("overall", report.get("overall_confidence", 0.0)))
            speaker = float(row.get("speaker", 0.0))
            points = float(row.get("points", 0.0))
            rationale = str(row.get("rationale", "unknown")).strip()
            labels = list(task.labels or [])
            if speaker < self._confidence_threshold:
                labels.append("low-confidence-speaker")
            if points < self._confidence_threshold:
                labels.append("low-confidence-story-points")
            if overall < self._confidence_threshold or force_human_review:
                labels.append("needs-human-review")
            task.labels = self._dedupe_labels(labels)
            if (overall < self._confidence_threshold or force_human_review) and not task.quotes:
                task.quotes = [f"confidence={overall:.2f}; rationale={rationale}"]
        return result

    @staticmethod
    def _dedupe_labels(labels: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for label in labels:
            clean = label.strip().lower()
            if clean and clean not in seen:
                seen.add(clean)
                out.append(clean[:64])
        return out[:20]

    @staticmethod
    def _validate_assignees(result: ExtractionResult, valid_speakers: list[str] | None) -> ExtractionResult:
        if not valid_speakers:
            return result
        for task in result.tasks:
            if task.assignee_name:
                task.assignee_name = _fuzzy_match_speaker(task.assignee_name, valid_speakers)
        return result

    @staticmethod
    def _parse_or_repair_response(llm, payload: str) -> ExtractionResult:
        try:
            return ExtractionResult.model_validate(json.loads(payload))
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("LLM payload failed validation. Attempting salvage/repair.", exc_info=exc)
            salvaged = LLMExtractor._salvage_tasks(payload)
            if salvaged:
                return salvaged
            repaired = llm.invoke(
                [
                    SystemMessage(content="You repair JSON to satisfy a strict Pydantic schema. Return valid JSON only."),
                    HumanMessage(content=f"Original completion:\n```{payload}```\nValidation error:\n```{exc}```"),
                ]
            ).content
            return ExtractionResult.model_validate(json.loads(repaired))

    @staticmethod
    def _salvage_tasks(payload: str | Mapping[str, Any]) -> ExtractionResult | None:
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
        except Exception:
            return None
        if not isinstance(data, Mapping):
            return None
        raw_tasks = data.get("tasks")
        if not isinstance(raw_tasks, list):
            return None
        valid: list[Task] = []
        for raw in raw_tasks:
            if not isinstance(raw, Mapping):
                continue
            clean: MutableMapping[str, Any] = dict(raw)
            assignee = clean.get("assignee_name")
            if isinstance(assignee, str) and not assignee.strip():
                clean["assignee_name"] = None
            try:
                valid.append(Task.model_validate(clean))
            except ValidationError:
                continue
        return ExtractionResult(tasks=valid) if valid else None
