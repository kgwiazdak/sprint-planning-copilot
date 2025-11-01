import json
import os
import re
from typing import Dict, Any

from .schemas import ExtractionResult

USE_MOCK = os.getenv("MOCK_LLM", "1") == "1"

class Extractor:
    def _mock_extract(self, transcript: str) -> Dict[str, Any]:
        lines = [l.strip() for l in transcript.splitlines() if l.strip()]
        tasks = []
        for i, line in enumerate(lines):
            if re.match(r'^(-|\*|TODO|ACTION)', line, re.I):
                summary = re.sub(r'^(-|\*|TODO:?|ACTION:?)\s*', '', line, flags=re.I)[:300]
                if not summary:
                    summary = f"Task from meeting line {i + 1}"
                tasks.append({
                    "summary": summary,
                    "description": f"Auto-extracted from transcript line {i + 1}.\n\nQuote: \"{line}\"",
                    "issue_type": "Task",
                    "assignee_name": None,
                    "priority": "Medium",
                    "story_points": None,
                    "labels": ["meeting-generated"],
                    "links": [],
                    "quotes": [line],
                })
        if not tasks:
            tasks = [{
                "summary": "Review meeting outcomes and create Jira tasks",
                "description": "No bullet-like items found. Review transcript and split into actionable tasks.",
                "issue_type": "Task",
                "assignee_name": None,
                "priority": "Medium",
                "story_points": None,
                "labels": ["meeting-generated"],
                "links": [],
                "quotes": [],
            }]
        return {"tasks": tasks}


    def _llm_chain(self, transcript: str) -> Dict[str, Any]:
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_openai import AzureChatOpenAI, ChatOpenAI
        except Exception:
            return _mock_extract(transcript)

        provider = os.getenv("LLM_PROVIDER", "azure").lower()
        if provider == "azure":
            llm = AzureChatOpenAI(
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
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
        except Exception:
            # Attempt automatic repair by asking the model to return only valid JSON
            fix_messages = ChatPromptTemplate.from_messages([
                ("system", "You repair JSON. Return valid JSON only, nothing else."),
                ("human", f"Repair this into valid JSON matching the schema:```{resp}```")
            ])
            resp2 = (fix_messages | llm).invoke({}).content
            data = json.loads(resp2)
        return data


    def extract_tasks_llm(self, transcript: str) -> ExtractionResult:
        data = self._mock_extract(transcript) if USE_MOCK else self._llm_chain(transcript)
        return ExtractionResult(**data)
