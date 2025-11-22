import json
import logging
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Mapping, MutableMapping, Any
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from pydantic import ValidationError

from backend.schemas import ExtractionResult, Task

logger = logging.getLogger(__name__)


def _extract_speakers_from_transcript(transcript: str) -> list[str]:
    """Extract speaker labels from diarized transcript lines.

    Lines look like "Speaker Name: text", where the name comes from intro filenames.
    """
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
    """Mirror intro filename parsing used by the transcriber."""
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
    """Return names derived from intro_* files so we can map partial matches to full names."""
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
    """If only first/last name is present, expand to full name when uniquely resolvable."""
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

    # Keep original extracted order
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

    return resolved


def _fuzzy_match_speaker(name: str, valid_speakers: list[str], threshold: float = 0.6) -> str | None:
    """Find the best matching speaker using fuzzy string matching.

    Returns the matched speaker name if similarity exceeds threshold, otherwise None.
    """
    if not name or not valid_speakers:
        return None

    name_lower = name.lower().strip()
    best_match = None
    best_score = 0.0

    for speaker in valid_speakers:
        speaker_lower = speaker.lower()
        # Exact match (case-insensitive)
        if name_lower == speaker_lower:
            return speaker

        # Check if name is a substring (e.g., "Adrian" matches "Adrian Puchacki")
        if name_lower in speaker_lower or speaker_lower in name_lower:
            score = len(name_lower) / max(len(speaker_lower), 1)
            if score > best_score:
                best_score = score
                best_match = speaker
                continue

        # Fuzzy matching
        score = SequenceMatcher(None, name_lower, speaker_lower).ratio()
        if score > best_score:
            best_score = score
            best_match = speaker

    if best_score >= threshold:
        return best_match
    return None


class LLMExtractor:
    @staticmethod
    def _llm_chain(transcript: str, valid_speakers: list[str] | None = None) -> ExtractionResult:
        provider = os.getenv("LLM_PROVIDER", "azure").lower()
        if valid_speakers is None:
            valid_speakers = _augment_with_known_voices(_extract_speakers_from_transcript(transcript))

        if provider == "azure":
            api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
            azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
            azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

            if not azure_deployment:
                raise RuntimeError(
                    "AZURE_OPENAI_DEPLOYMENT environment variable must be set to use Azure OpenAI."
                )
            if not azure_endpoint:
                raise RuntimeError(
                    "AZURE_OPENAI_ENDPOINT environment variable must be set to use Azure OpenAI."
                )

            llm = AzureChatOpenAI(
                api_version=api_version,
                azure_deployment=azure_deployment,
                azure_endpoint=azure_endpoint,
                temperature=0.1,
            )
        else:
            llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0.1)

        # Build speaker constraint for the prompt
        speaker_constraint = ""
        if valid_speakers:
            speaker_list = ", ".join(f'"{s}"' for s in valid_speakers)
            speaker_constraint = (
                f"\n\nIMPORTANT: The only valid assignees are the identified speakers from the meeting: [{speaker_list}]. "
                "assignee_name MUST be exactly one of these names or null. Do NOT use any other names."
            )

        system = (
            "You are an Agile Product Owner. Extract Jira-ready tasks from meeting transcripts. "
            "Return STRICT JSON following the schema:\n"
            "{{\n  \"tasks\": [\n    {{\n      \"summary\": str, \"description\": str, "
            "\"issue_type\": one of [\"Story\",\"Task\",\"Bug\",\"Spike\"], "
            "\"assignee_name\": str|null, \"priority\": one of [\"Low\",\"Medium\",\"High\"], "
            "\"story_points\": int|null, \"labels\": [str], \"links\": [str], \"quotes\": [str]\n    }}\n  ]\n}}"
            "\nIf no assignee, set null. Use quotes to include short verbatim snippets from the transcript that justify each task."
            f"{speaker_constraint}"
        )
        human = f"Transcript:\n{transcript}\n---\nReturn only JSON, no prose."
        messages = [SystemMessage(content=system), HumanMessage(content=human)]

        raw_response = llm.invoke(messages).content
        result = LLMExtractor._parse_or_repair_response(llm, raw_response)
        return LLMExtractor._validate_assignees(result, valid_speakers)

    @staticmethod
    def _validate_assignees(result: ExtractionResult, valid_speakers: list[str] | None) -> ExtractionResult:
        """Ensure all assignee_name values are valid speakers or set to None."""
        if not valid_speakers:
            return result

        for task in result.tasks:
            if task.assignee_name:
                matched = _fuzzy_match_speaker(task.assignee_name, valid_speakers)
                if matched:
                    task.assignee_name = matched
                else:
                    logger.warning(
                        "Assignee '%s' not found in valid speakers %s, setting to None",
                        task.assignee_name,
                        valid_speakers,
                    )
                    task.assignee_name = None
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
        """Best-effort recovery: keep all individually valid tasks even if the whole payload failed."""
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
            # Avoid failing the whole batch due to trivial empty strings
            sanitized: MutableMapping[str, Any] = dict(raw_task)
            assignee = sanitized.get("assignee_name")
            if isinstance(assignee, str) and not assignee.strip():
                sanitized["assignee_name"] = None
            try:
                valid_tasks.append(Task.model_validate(sanitized))
            except ValidationError:
                continue
        return ExtractionResult(tasks=valid_tasks) if valid_tasks else None

    def extract(self, transcript: str) -> ExtractionResult:
        return self._llm_chain(transcript)
