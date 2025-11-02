"""Task extraction powered by Azure OpenAI."""

from __future__ import annotations

import os

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import AzureChatOpenAI

from .schemas import ExtractionResult


class Extractor:
    """LLM-backed extractor that integrates with Azure OpenAI."""

    def __init__(self) -> None:
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY")

        missing = [name for name, value in {
            "AZURE_OPENAI_DEPLOYMENT": deployment,
            "AZURE_OPENAI_ENDPOINT": endpoint,
            "AZURE_OPENAI_API_KEY": api_key,
        }.items() if not value]

        if missing:
            raise RuntimeError(
                "Missing Azure OpenAI configuration: " + ", ".join(missing)
            )

        self._llm = AzureChatOpenAI(
            api_key=api_key,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
            azure_deployment=deployment,
            azure_endpoint=endpoint,
            temperature=0.1,
        )
        self._parser = PydanticOutputParser(pydantic_object=ExtractionResult)
        self._prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an Agile Product Owner. Extract Jira-ready tasks from meeting transcripts. "
                    "Use the provided format instructions to guarantee the JSON schema.",
                ),
                (
                    "human",
                    "Transcript:\n{transcript}\n---\n{format_instructions}",
                ),
            ]
        ).partial(format_instructions=self._parser.get_format_instructions())

    def _invoke_model(self, transcript: str) -> ExtractionResult:
        chain = self._prompt | self._llm | self._parser
        return chain.invoke({"transcript": transcript})

    def extract_tasks_llm(self, transcript: str) -> ExtractionResult:
        """Extract tasks from a transcript using Azure OpenAI."""

        result = self._invoke_model(transcript)
        if isinstance(result, ExtractionResult):
            return result
        if isinstance(result, dict):
            return ExtractionResult(**result)
        raise TypeError("Unexpected result type from Azure OpenAI chain")
