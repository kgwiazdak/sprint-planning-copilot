import json
import logging
import os
from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from .schemas import ExtractionResult

logger = logging.getLogger(__name__)


class Extractor:
    def _llm_chain(self, transcript: str) -> Dict[str, Any]:
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
            "{\n  \"tasks\": [\n    {\n      \"summary\": str, \"description\": str, "
            "\"issue_type\": one of [\"Story\",\"Task\",\"Bug\",\"Spike\"], "
            "\"assignee_name\": str|null, \"priority\": one of [\"Low\",\"Medium\",\"High\"], "
            "\"story_points\": int|null, \"labels\": [str], \"links\": [str], \"quotes\": [str]\n    }\n  ]\n}"
            "\nIf no assignee, set null. Use quotes to include short verbatim snippets from the transcript that justify each task."
        )
        human = "Transcript:\n{transcript}\n---\nReturn only JSON, no prose."
        prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
        chain = prompt | llm

        resp = chain.invoke({"transcript": transcript}).content
        try:
            data = json.loads(resp)
        except Exception as exc:
            logger.warning("LLM returned invalid JSON, attempting automatic repair", exc_info=exc)
            # Attempt automatic repair by asking the model to return only valid JSON
            fix_messages = ChatPromptTemplate.from_messages([
                ("system", "You repair JSON. Return valid JSON only, nothing else."),
                ("human", f"Repair this into valid JSON matching the schema:```{resp}```")
            ])
            resp2 = (fix_messages | llm).invoke({}).content
            data = json.loads(resp2)
        return data


    def extract_tasks_llm(self, transcript: str) -> ExtractionResult:
        data = self._llm_chain(transcript)
        return ExtractionResult(**data)
