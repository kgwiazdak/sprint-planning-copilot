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

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from pydantic import ValidationError

from backend.schemas import ExtractionResult, Task

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency in some environments
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - fallback when langgraph isn't installed
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

    def _title_token(token: str) -> str:
        if "-" not in token:
            return token.capitalize()
        return "-".join(part.capitalize() for part in token.split("-") if part)

    parts = [_title_token(token) for token in stem.split() if token]
    return " ".join(parts) if parts else "Speaker"


def _known_voice_names(intro_dir: str | Path | None = None, pattern: str | None = None) -> list[str]:
    directory = Path(intro_dir or os.getenv("INTRO_AUDIO_DIR", "data/voices"))
    glob_pattern = pattern or os.getenv("INTRO_AUDIO_PATTERN", "intro_*.*")
    if not directory.exists():
        return []
    names: list[str] = []
    seen: set[str] = set()
    for path in sorted(directory.glob(glob_pattern)):
        if not path.is_file():
            continue
        name = _role_from_intro_filename(path)
        key = name.lower().strip()
        if key and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def _augment_with_known_voices(extracted: list[str]) -> list[str]:
    known = _known_voice_names()
    if not known:
        return extracted

    resolved: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        norm = name.strip()
        key = norm.lower()
        if norm and key not in seen:
            seen.add(key)
            resolved.append(norm)

    for name in extracted:
        _add(name)

    for name in extracted:
        tokens = name.strip().split()
        if len(tokens) != 1:
            continue
        token = tokens[0].lower()
        candidates = [
            full
            for full in known
            if full.lower() == token
            or full.lower().startswith(f"{token} ")
            or full.lower().endswith(f" {token}")
        ]
        if len(candidates) == 1:
            _add(candidates[0])

    if len(resolved) <= 1 and known:
        for name in known:
            _add(name)

    return resolved


def _fuzzy_match_speaker(name: str, valid_speakers: list[str], threshold: float = 0.6) -> str | None:
    if not name or not valid_speakers:
        return None

    name_lower = name.lower().strip()
    best_match = None
    best_score = 0.0

    for speaker in valid_speakers:
        speaker_lower = speaker.lower()
        if name_lower == speaker_lower:
            return speaker

        if name_lower in speaker_lower or speaker_lower in name_lower:
            score = len(name_lower) / max(len(speaker_lower), 1)
            if score > best_score:
                best_score = score
                best_match = speaker
                continue

        score = SequenceMatcher(None, name_lower, speaker_lower).ratio()
        if score > best_score:
            best_score = score
            best_match = speaker

    if best_score >= threshold:
        return best_match
    return None


class LLMExtractor:
    def __init__(self) -> None:
        self.last_timings: dict[str, float] = {}
        self._provider = os.getenv("LLM_PROVIDER", "openai").lower()
        self._runtime = os.getenv("AGENT_RUNTIME", "langgraph").lower()
        self._confidence_threshold = float(os.getenv("AGENT_CONFIDENCE_THRESHOLD", "0.75"))
        self._max_low_conf_task_ratio = float(os.getenv("AGENT_MAX_LOW_CONF_TASK_RATIO", "0.5"))
        self._checkpointer = MemorySaver() if LANGGRAPH_AVAILABLE and MemorySaver else None
        self._graph = self._build_graph() if self._runtime == "langgraph" else None

        if self._runtime == "langgraph" and not LANGGRAPH_AVAILABLE:
            logger.warning("AGENT_RUNTIME=langgraph but 'langgraph' package is unavailable; falling back to sequential extraction.")

    def extract(self, transcript: str) -> ExtractionResult:
        if self._graph:
            thread_id = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:16]
            state = self._graph.invoke(
                {"transcript": transcript},
                config={"configurable": {"thread_id": thread_id}},
            )
            result = state["result"]
            timings = dict(state.get("timings", {}))
            report = state.get("confidence_report", {})
            timings["agentic_overall_confidence"] = float(report.get("overall_confidence", 0.0))
            timings["agentic_low_confidence_tasks"] = float(report.get("low_confidence_tasks", 0))
            self.last_timings = timings
            return result

        result, timings = self._run_sequential(transcript)
        self.last_timings = timings
        return result

    def _build_graph(self):
        if not LANGGRAPH_AVAILABLE or StateGraph is None:
            return None

        workflow = StateGraph(ExtractionGraphState)
        workflow.add_node("context_agent", self._node_context_agent)
        workflow.add_node("planner_agent", self._node_planner_agent)
        workflow.add_node("parser_agent", self._node_parser_agent)
        workflow.add_node("critic_agent", self._node_critic_agent)
        workflow.add_node("policy_standard", self._node_policy_standard)
        workflow.add_node("policy_low_confidence", self._node_policy_low_confidence)

        workflow.add_edge(START, "context_agent")
        workflow.add_edge("context_agent", "planner_agent")
        workflow.add_edge("planner_agent", "parser_agent")
        workflow.add_edge("parser_agent", "critic_agent")
        workflow.add_conditional_edges(
            "critic_agent",
            self._route_after_critic,
            {
                "policy_standard": "policy_standard",
                "policy_low_confidence": "policy_low_confidence",
            },
        )
        workflow.add_edge("policy_standard", END)
        workflow.add_edge("policy_low_confidence", END)

        return workflow.compile(checkpointer=self._checkpointer)

    def _run_sequential(self, transcript: str) -> tuple[ExtractionResult, dict[str, float]]:
        state: ExtractionGraphState = {"transcript": transcript}
        state.update(self._node_context_agent(state))
        state.update(self._node_planner_agent(state))
        state.update(self._node_parser_agent(state))
        state.update(self._node_critic_agent(state))
        low_path = self._route_after_critic(state) == "policy_low_confidence"
        if low_path:
            state.update(self._node_policy_low_confidence(state))
        else:
            state.update(self._node_policy_standard(state))
        return state["result"], state.get("timings", {})

    def _build_llm(self, role: str):
        model_env_map = {
            "planner": os.getenv("AGENT_PLANNER_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")),
            "critic": os.getenv("AGENT_CRITIC_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")),
        }
        temperature = 0.1 if role == "planner" else 0.0
        provider = self._provider
        if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
            if os.getenv("AZURE_OPENAI_DEPLOYMENT") and os.getenv("AZURE_OPENAI_ENDPOINT"):
                logger.warning("OPENAI_API_KEY is missing; falling back to Azure OpenAI for %s agent.", role)
                provider = "azure"
        if provider == "azure":
            api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
            azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
            azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            if not azure_deployment or not azure_endpoint:
                raise RuntimeError("Azure OpenAI requires AZURE_OPENAI_DEPLOYMENT and AZURE_OPENAI_ENDPOINT.")
            return AzureChatOpenAI(
                api_version=api_version,
                azure_deployment=azure_deployment,
                azure_endpoint=azure_endpoint,
                temperature=temperature,
            )
        return ChatOpenAI(model=model_env_map.get(role, "gpt-4o-mini"), temperature=temperature)

    def _node_context_agent(self, state: ExtractionGraphState) -> dict[str, Any]:
        transcript = state["transcript"]
        valid_speakers = _augment_with_known_voices(_extract_speakers_from_transcript(transcript))
        return {"valid_speakers": valid_speakers}

    def _node_planner_agent(self, state: ExtractionGraphState) -> dict[str, Any]:
        llm = self._build_llm("planner")
        transcript = state["transcript"]
        valid_speakers = state.get("valid_speakers", [])
        messages = self._build_planner_messages(transcript, valid_speakers)
        raw_response, timings = LLMExtractor._invoke_with_timings(llm, messages)
        base_timings = dict(state.get("timings", {}))
        base_timings.update(
            {
                "latency_ms_planner": timings.get("latency_ms_llm", 0.0),
                "llm_provider": self._provider,
                "llm_model_name": getattr(llm, "model_name", None) or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            }
        )
        return {"planner_raw": raw_response, "timings": base_timings}

    def _node_parser_agent(self, state: ExtractionGraphState) -> dict[str, Any]:
        planner_raw = state.get("planner_raw", "")
        llm = self._build_llm("planner")
        result = LLMExtractor._parse_or_repair_response(llm, planner_raw)
        valid_speakers = state.get("valid_speakers", [])
        result = LLMExtractor._validate_assignees(result, valid_speakers)
        return {"result": result}

    def _node_critic_agent(self, state: ExtractionGraphState) -> dict[str, Any]:
        llm = self._build_llm("critic")
        transcript = state["transcript"]
        result = state["result"]
        valid_speakers = state.get("valid_speakers", [])
        started = time.perf_counter()
        report = self._heuristic_confidence_report(transcript, result, valid_speakers)
        try:
            messages = self._build_critic_messages(transcript, result, valid_speakers)
            raw, _timings = LLMExtractor._invoke_with_timings(llm, messages)
            model_report = self._parse_critic_report(raw, result)
            if model_report:
                report = model_report
        except Exception:
            logger.debug("Critic agent fallback to heuristic confidence report.", exc_info=True)
        elapsed = (time.perf_counter() - started) * 1000
        timings = dict(state.get("timings", {}))
        timings["latency_ms_critic"] = elapsed
        return {"confidence_report": report, "timings": timings}

    def _node_policy_standard(self, state: ExtractionGraphState) -> dict[str, Any]:
        result = self._apply_confidence_policy(
            result=state["result"],
            report=state.get("confidence_report", {}),
            force_human_review=False,
        )
        return {"result": result}

    def _node_policy_low_confidence(self, state: ExtractionGraphState) -> dict[str, Any]:
        result = self._apply_confidence_policy(
            result=state["result"],
            report=state.get("confidence_report", {}),
            force_human_review=True,
        )
        return {"result": result}

    def _route_after_critic(self, state: ExtractionGraphState) -> str:
        report = state.get("confidence_report", {})
        overall = float(report.get("overall_confidence", 0.0))
        low_conf_tasks = int(report.get("low_confidence_tasks", 0))
        total_tasks = max(1, len(state["result"].tasks))
        low_ratio = low_conf_tasks / total_tasks
        if overall < self._confidence_threshold or low_ratio >= self._max_low_conf_task_ratio:
            return "policy_low_confidence"
        return "policy_standard"

    @staticmethod
    def _build_planner_messages(transcript: str, valid_speakers: list[str]) -> list:
        speaker_constraint = ""
        if valid_speakers:
            speaker_list = ", ".join(f'"{s}"' for s in valid_speakers)
            speaker_constraint = (
                f"\n\nIMPORTANT: The only valid assignees are [{speaker_list}]. "
                "assignee_name MUST be one of these names or null."
            )
        system = (
            "You are PlannerAgent. Extract Jira-ready tasks from the transcript and return STRICT JSON:\n"
            "{"
            "\"tasks\": ["
            "{"
            "\"summary\": str, \"description\": str, "
            "\"issue_type\": one of [\"Story\",\"Task\",\"Bug\",\"Spike\"], "
            "\"assignee_name\": str|null, \"priority\": one of [\"Low\",\"Medium\",\"High\"], "
            "\"story_points\": int, \"labels\": [str], \"links\": [str], \"quotes\": [str]"
            "}"
            "]"
            "}"
            "\nRules:"
            "\n- story_points must be an integer."
            "\n- use transcript evidence in quotes."
            "\n- if assignee unknown set assignee_name=null."
            f"{speaker_constraint}"
        )
        human = f"Transcript:\n{transcript}\n---\nReturn only JSON."
        return [SystemMessage(content=system), HumanMessage(content=human)]

    @staticmethod
    def _build_critic_messages(transcript: str, result: ExtractionResult, valid_speakers: list[str]) -> list:
        tasks_payload = [
            {
                "summary": task.summary,
                "assignee_name": task.assignee_name,
                "story_points": task.story_points,
                "quotes": task.quotes,
            }
            for task in result.tasks
        ]
        excerpt = transcript[:8000]
        system = (
            "You are CriticAgent. Assess extraction confidence.\n"
            "Return STRICT JSON:\n"
            "{"
            "\"overall_confidence\": float(0-1), "
            "\"tasks\": ["
            "{"
            "\"summary\": str, \"overall\": float(0-1), "
            "\"speaker\": float(0-1), \"points\": float(0-1), \"rationale\": str"
            "}"
            "]"
            "}"
        )
        human = (
            f"Known speakers: {valid_speakers}\n"
            f"Tasks JSON: {json.dumps(tasks_payload, ensure_ascii=True)}\n"
            f"Transcript excerpt:\n{excerpt}\n"
            "Return only JSON."
        )
        return [SystemMessage(content=system), HumanMessage(content=human)]

    @staticmethod
    def _parse_critic_report(raw: str, result: ExtractionResult) -> dict[str, Any] | None:
        data = json.loads(raw)
        tasks = data.get("tasks")
        if not isinstance(tasks, list):
            return None
        mapped: dict[str, TaskConfidence] = {}
        for item in tasks:
            if not isinstance(item, Mapping):
                continue
            summary = str(item.get("summary", "")).strip()
            if not summary:
                continue
            mapped[summary] = TaskConfidence(
                summary=summary,
                overall=float(item.get("overall", 0.0)),
                speaker=float(item.get("speaker", 0.0)),
                points=float(item.get("points", 0.0)),
                rationale=str(item.get("rationale", "")).strip(),
            )
        normalized: list[dict[str, Any]] = []
        low_conf = 0
        for task in result.tasks:
            row = mapped.get(task.summary)
            if not row:
                row = TaskConfidence(
                    summary=task.summary,
                    overall=0.6,
                    speaker=0.6,
                    points=0.6,
                    rationale="critic_default",
                )
            normalized.append(
                {
                    "summary": row.summary,
                    "overall": max(0.0, min(1.0, row.overall)),
                    "speaker": max(0.0, min(1.0, row.speaker)),
                    "points": max(0.0, min(1.0, row.points)),
                    "rationale": row.rationale,
                }
            )
            if row.overall < 0.75:
                low_conf += 1
        overall = float(data.get("overall_confidence", 0.0))
        if overall <= 0:
            overall = sum(item["overall"] for item in normalized) / max(1, len(normalized))
        return {
            "overall_confidence": max(0.0, min(1.0, overall)),
            "tasks": normalized,
            "low_confidence_tasks": low_conf,
        }

    def _heuristic_confidence_report(
        self,
        transcript: str,
        result: ExtractionResult,
        valid_speakers: list[str],
    ) -> dict[str, Any]:
        transcript_lower = transcript.lower()
        reports: list[dict[str, Any]] = []
        low_conf = 0
        for task in result.tasks:
            speaker_conf = 1.0
            if task.assignee_name:
                speaker_match = _fuzzy_match_speaker(task.assignee_name, valid_speakers, threshold=0.75)
                speaker_conf = 0.95 if speaker_match else 0.45
            elif valid_speakers:
                speaker_conf = 0.5

            points_conf = 0.95
            if task.story_points is None:
                points_conf = 0.4
            elif not re.search(r"\b(point|points|sp|story points?)\b", transcript_lower):
                points_conf = 0.6

            quote_conf = 0.85 if task.quotes else 0.55
            overall = round((speaker_conf * 0.45) + (points_conf * 0.35) + (quote_conf * 0.2), 3)
            if overall < self._confidence_threshold:
                low_conf += 1
            reports.append(
                {
                    "summary": task.summary,
                    "overall": overall,
                    "speaker": round(speaker_conf, 3),
                    "points": round(points_conf, 3),
                    "rationale": "heuristic",
                }
            )

        overall_conf = round(sum(row["overall"] for row in reports) / max(1, len(reports)), 3)
        return {
            "overall_confidence": overall_conf,
            "tasks": reports,
            "low_confidence_tasks": low_conf,
        }

    def _apply_confidence_policy(
        self,
        *,
        result: ExtractionResult,
        report: Mapping[str, Any],
        force_human_review: bool,
    ) -> ExtractionResult:
        tasks_conf = report.get("tasks") if isinstance(report.get("tasks"), list) else []
        by_summary = {
            str(item.get("summary", "")).strip(): item
            for item in tasks_conf
            if isinstance(item, Mapping) and str(item.get("summary", "")).strip()
        }
        threshold = self._confidence_threshold
        for task in result.tasks:
            row = by_summary.get(task.summary, {})
            overall = float(row.get("overall", report.get("overall_confidence", 0.0)))
            speaker = float(row.get("speaker", 0.0))
            points = float(row.get("points", 0.0))
            rationale = str(row.get("rationale", "unknown")).strip()

            labels = list(task.labels or [])
            if speaker < threshold:
                labels.append("low-confidence-speaker")
            if points < threshold:
                labels.append("low-confidence-story-points")
            if overall < threshold or force_human_review:
                labels.append("needs-human-review")
            labels = self._dedupe_labels(labels)
            task.labels = labels

            if (overall < threshold or force_human_review) and not task.quotes:
                task.quotes = [f"confidence={overall:.2f}; rationale={rationale}"]
        return result

    @staticmethod
    def _dedupe_labels(labels: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for label in labels:
            cleaned = label.strip().lower()
            if not cleaned:
                continue
            if cleaned not in seen:
                seen.add(cleaned)
                unique.append(cleaned[:64])
        return unique[:20]

    @staticmethod
    def _validate_assignees(result: ExtractionResult, valid_speakers: list[str] | None) -> ExtractionResult:
        if not valid_speakers:
            return result
        for task in result.tasks:
            if task.assignee_name:
                matched = _fuzzy_match_speaker(task.assignee_name, valid_speakers)
                task.assignee_name = matched
        return result

    @staticmethod
    def _parse_or_repair_response(llm, payload: str) -> ExtractionResult:
        try:
            data = json.loads(payload)
            return ExtractionResult.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("LLM payload failed validation. Attempting salvage/repair.", exc_info=exc)
            salvaged = LLMExtractor._salvage_tasks(payload)
            if salvaged:
                return salvaged
            repair_messages = [
                SystemMessage(
                    content=(
                        "You repair JSON to satisfy a strict Pydantic schema. "
                        "Return valid JSON only, no prose."
                    )
                ),
                HumanMessage(
                    content=(
                        "Original completion:\n```"
                        f"{payload}"
                        "```"
                        "\nValidation error:\n```"
                        f"{exc}"
                        "```"
                        "\nReturn JSON matching the schema that passes validation."
                    )
                ),
            ]
            repaired = llm.invoke(repair_messages).content
            data = json.loads(repaired)
            return ExtractionResult.model_validate(data)

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

        valid_tasks: list[Task] = []
        for raw_task in raw_tasks:
            if not isinstance(raw_task, Mapping):
                continue
            sanitized: MutableMapping[str, Any] = dict(raw_task)
            assignee = sanitized.get("assignee_name")
            if isinstance(assignee, str) and not assignee.strip():
                sanitized["assignee_name"] = None
            try:
                valid_tasks.append(Task.model_validate(sanitized))
            except ValidationError:
                continue
        return ExtractionResult(tasks=valid_tasks) if valid_tasks else None

    @staticmethod
    def _invoke_with_timings(llm, messages) -> tuple[str, dict[str, float]]:
        started = time.perf_counter()
        content_parts: list[str] = []
        first_token_time = None
        try:
            for chunk in llm.stream(messages):
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                piece = getattr(chunk, "content", None) or getattr(getattr(chunk, "message", None), "content", "") or ""
                if piece:
                    content_parts.append(piece)
            finished = time.perf_counter()
            ttft_ms = ((first_token_time or finished) - started) * 1000
            ttl_ms = (finished - started) * 1000
            return "".join(content_parts) or "", {
                "llm_ttft_ms": ttft_ms,
                "llm_ttl_ms": ttl_ms,
                "latency_ms_llm": ttl_ms,
            }
        except Exception:
            logger.debug("LLM streaming unavailable, falling back to blocking invoke.", exc_info=True)
            completion = llm.invoke(messages).content
            finished = time.perf_counter()
            ttl_ms = (finished - started) * 1000
            return completion, {
                "llm_ttft_ms": ttl_ms,
                "llm_ttl_ms": ttl_ms,
                "latency_ms_llm": ttl_ms,
            }
