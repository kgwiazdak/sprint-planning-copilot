from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def configure_langsmith() -> None:
    """Enable LangSmith/LangChain tracing from env flags in a single place."""
    enabled = os.getenv("LANGSMITH_TRACING", "false").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return

    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGCHAIN_PROJECT", "sprint-planning-copilot"))
    os.environ.setdefault("LANGSMITH_PROJECT", os.getenv("LANGSMITH_PROJECT", "sprint-planning-copilot"))

    endpoint = os.getenv("LANGSMITH_ENDPOINT")
    if endpoint:
        os.environ.setdefault("LANGSMITH_ENDPOINT", endpoint)

    api_key_present = bool(os.getenv("LANGSMITH_API_KEY"))
    if not api_key_present:
        logger.warning("LANGSMITH_TRACING is enabled but LANGSMITH_API_KEY is missing.")

