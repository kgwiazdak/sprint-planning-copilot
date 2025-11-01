import json
import logging
import os
import re
from typing import Any, Dict, Optional

from .schemas import ExtractionResult

logger = logging.getLogger(__name__)

USE_MOCK = os.getenv("MOCK_LLM", "0") == "1"


class Extractor:
    def __init__(self) -> None:
        self.model_id = os.getenv("DEEPSEEK_MODEL", "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B")
        self.max_new_tokens = int(os.getenv("DEEPSEEK_MAX_NEW_TOKENS", "1024"))
        self.temperature = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.1"))
        self.device = os.getenv("DEEPSEEK_DEVICE", "auto").lower()
        self._tokenizer = None
        self._model = None
        self._torch = None

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

    def _ensure_model(self) -> bool:
        if self._tokenizer is not None and self._model is not None and self._torch is not None:
            return True
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch
        except ImportError:
            logger.warning("transformers not available, falling back to mock extractor")
            return False

        logger.info("Loading DeepSeek model %s", self.model_id)
        tokenizer = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=True)

        device_map: Optional[Dict[str, str]] = None
        torch_dtype = torch.float16
        if self.device == "cpu":
            device_map = {"": "cpu"}
            torch_dtype = torch.float32
        elif self.device != "auto":
            device_map = {"": self.device}

        model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            trust_remote_code=True,
            device_map=device_map or "auto",
            torch_dtype=torch_dtype,
        )
        model.eval()

        self._tokenizer = tokenizer
        self._model = model
        self._torch = torch
        return True

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

    def _deepseek_generate(self, transcript: str) -> Dict[str, Any]:
        if not self._ensure_model():
            return self._mock_extract(transcript)

        assert self._tokenizer is not None and self._model is not None and self._torch is not None
        torch = self._torch

        system_prompt = (
            "You are an Agile Product Owner. Extract Jira-ready tasks from meeting transcripts. "
            "Return STRICT JSON following the schema:\n"
            "{\n  \"tasks\": [\n    {\n      \"summary\": str, \"description\": str, \"issue_type\": one of [\"Story\",\"Task\",\"Bug\",\"Spike\"], "
            "\"assignee_name\": str|null, \"priority\": one of [\"Low\",\"Medium\",\"High\"], \"story_points\": int|null, \"labels\": [str], \"links\": [str], \"quotes\": [str]\n    }\n  ]\n}"
            "\nIf no assignee, set null. Use quotes to include short verbatim snippets from the transcript that justify each task."
        )
        user_prompt = (
            "Transcript:\n"
            f"{transcript}\n"
            "---\nReturn only valid JSON, no additional commentary."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        prompt_text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer(
            prompt_text,
            return_tensors="pt",
            padding=False,
            add_special_tokens=False,
        )
        model_device = next(self._model.parameters()).device
        inputs = {k: v.to(model_device) for k, v in inputs.items()}

        with torch.no_grad():
            output = self._model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                temperature=self.temperature,
                do_sample=False,
                eos_token_id=self._tokenizer.eos_token_id,
            )

        generated_tokens = output[0, inputs["input_ids"].shape[-1] :]
        response_text = self._tokenizer.decode(
            generated_tokens, skip_special_tokens=True
        ).strip()

        try:
            return self._parse_json_response(response_text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse DeepSeek response as JSON: %s", exc)
            logger.debug("DeepSeek raw response: %s", response_text)
            return self._mock_extract(transcript)

    def extract_tasks_llm(self, transcript: str) -> ExtractionResult:
        data = self._mock_extract(transcript) if USE_MOCK else self._deepseek_generate(transcript)
        return ExtractionResult(**data)
