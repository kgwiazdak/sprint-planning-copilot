import json
import logging
import os
import re
from typing import Any, Dict

import requests
from requests import RequestException

from .schemas import ExtractionResult

logger = logging.getLogger(__name__)

USE_MOCK = os.getenv("MOCK_LLM", "0") == "1"

_DEFAULT_MODEL_CONFIG = {
    "deepseek": {
        "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        "api_base": "http://deepseek:8000/v1",
    },
    "phi": {
        "model": "microsoft/Phi-3.5-mini-instruct",
        "api_base": "http://phi:8000/v1",
    },
}


class Extractor:
    def __init__(self) -> None:
        variant = os.getenv("LLM_MODEL_VARIANT", "deepseek").lower()
        default_config = _DEFAULT_MODEL_CONFIG.get(variant, _DEFAULT_MODEL_CONFIG["deepseek"])
        self.model_id = os.getenv("LLM_MODEL_ID", default_config["model"])
        self.api_base = os.getenv("LLM_API_BASE", default_config["api_base"]).rstrip("/")
        self.max_new_tokens = int(os.getenv("LLM_MAX_NEW_TOKENS", "1024"))
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
        self.timeout = float(os.getenv("LLM_TIMEOUT", "120"))
        self.api_key = os.getenv("LLM_API_KEY")

    def _mock_extract(self, transcript: str) -> Dict[str, Any]:
        lines = [l.strip() for l in transcript.splitlines() if l.strip()]
        tasks = []
        for i, line in enumerate(lines):
            if re.match(r"^(-|\*|TODO|ACTION)", line, re.I):
                summary = re.sub(r"^(-|\*|TODO:?|ACTION:?)\s*", "", line, flags=re.I)[:300]
                if not summary:
                    summary = f"Task from meeting line {i + 1}"
                tasks.append(
                    {
                        "summary": summary,
                        "description": f"Auto-extracted from transcript line {i + 1}.\n\nQuote: \"{line}\"",
                        "issue_type": "Task",
                        "assignee_name": None,
                        "priority": "Medium",
                        "story_points": None,
                        "labels": ["meeting-generated"],
                        "links": [],
                        "quotes": [line],
                    }
                )
        if not tasks:
            tasks = [
                {
                    "summary": "Review meeting outcomes and create Jira tasks",
                    "description": "No bullet-like items found. Review transcript and split into actionable tasks.",
                    "issue_type": "Task",
                    "assignee_name": None,
                    "priority": "Medium",
                    "story_points": None,
                    "labels": ["meeting-generated"],
                    "links": [],
                    "quotes": [],
                }
            ]
        return {"tasks": tasks}

    def _extract_json_block(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            stripped = text.strip("`")
            if stripped.lower().startswith("json"):
                stripped = stripped[4:]
            text = stripped.strip()
        if text.startswith("{") and text.rstrip().endswith("}"):
            return text
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in model response")
        return text[start : end + 1]

    def _parse_json_response(self, raw: str) -> Dict[str, Any]:
        candidate = self._extract_json_block(raw)
        return json.loads(candidate)

    def _llm_generate(self, transcript: str) -> Dict[str, Any]:
        system_prompt = (
            "You are an Agile Product Owner. Extract Jira-ready tasks from meeting transcripts. "
            "Return STRICT JSON following the schema:\n"
            "{\n  \"tasks\": [\n    {\n      \"summary\": str, \"description\": str, \"issue_type\": one of [\"Story\",\"Task\","
            "\"Bug\",\"Spike\"], "
            "\"assignee_name\": str|null, \"priority\": one of [\"Low\",\"Medium\",\"High\"], \"story_points\": int|null, \"labels\": [str], \"links\": [str], \"quotes\": [str]\n    }\n  ]\n}"
            "\nIf no assignee, set null. Use quotes to include short verbatim snippets from the transcript that justify each task."
        )
        user_prompt = (
            "Transcript:\n"
            f"{transcript}\n"
            "---\nReturn only valid JSON, no additional commentary."
        )

        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_new_tokens,
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = requests.post(
                f"{self.api_base}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except RequestException as exc:
            logger.warning("LLM HTTP request failed: %s", exc)
            return self._mock_extract(transcript)

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("Failed to decode LLM JSON payload: %s", exc)
            logger.debug("Raw LLM response text: %s", response.text)
            return self._mock_extract(transcript)

        choices = data.get("choices") or []
        if not choices:
            logger.warning("LLM response missing choices: %s", data)
            return self._mock_extract(transcript)

        response_text = choices[0].get("message", {}).get("content", "").strip()
        if not response_text:
            logger.warning("LLM returned empty content: %s", data)
            return self._mock_extract(transcript)

        try:
            return self._parse_json_response(response_text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse LLM response as JSON: %s", exc)
            logger.debug("LLM raw response: %s", response_text)
            return self._mock_extract(transcript)

    def extract_tasks_llm(self, transcript: str) -> ExtractionResult:
        data = self._mock_extract(transcript) if USE_MOCK else self._llm_generate(transcript)
        return ExtractionResult(**data)
