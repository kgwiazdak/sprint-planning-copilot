import json
import logging
import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from pydantic import ValidationError

from backend.schemas import ExtractionResult

logger = logging.getLogger(__name__)


class LLMExtractor:
    @staticmethod
    def _llm_chain(transcript: str) -> ExtractionResult:
        provider = os.getenv("LLM_PROVIDER", "azure").lower()

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
        system = (
            "You are an Agile Product Owner. Extract Jira-ready tasks from meeting transcripts. "
            "Return STRICT JSON following the schema:\n"
            "{{\n  \"tasks\": [\n    {{\n      \"summary\": str, \"description\": str, "
            "\"issue_type\": one of [\"Story\",\"Task\",\"Bug\",\"Spike\"], "
            "\"assignee_name\": str|null, \"priority\": one of [\"Low\",\"Medium\",\"High\"], "
            "\"story_points\": int|null, \"labels\": [str], \"links\": [str], \"quotes\": [str]\n    }}\n  ]\n}}"
            "\nIf no assignee, set null. Use quotes to include short verbatim snippets from the transcript that justify each task."
        )
        human = f"Transcript:\n{transcript}\n---\nReturn only JSON, no prose."
        messages = [SystemMessage(content=system), HumanMessage(content=human)]

        raw_response = llm.invoke(messages).content
        return Extractor._parse_or_repair_response(llm, raw_response)

    @staticmethod
    def _parse_or_repair_response(llm, payload: str) -> ExtractionResult:
        try:
            data = json.loads(payload)
            return ExtractionResult.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("LLM payload failed validation. Attempting repair.", exc_info=exc)
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

    def extract_tasks_llm(self, transcript: str) -> ExtractionResult:
        return self._llm_chain(transcript)

    def extract(self, transcript: str) -> ExtractionResult:
        return self._llm_chain(transcript)


# Backwards compatibility for older imports
Extractor = LLMExtractor
