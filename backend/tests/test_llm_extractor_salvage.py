from __future__ import annotations

import json

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langchain_openai")

from backend.infrastructure.llm.task_extractor import LLMExtractor
from backend.schemas import IssueType, Priority


class DummyLLM:
    def invoke(self, *_args, **_kwargs):
        raise AssertionError("Repair should not be called when salvage succeeds")


def _task(summary: str, description: str | None = "desc", assignee: str | None = "Alice"):
    return {
        "summary": summary,
        "description": description,
        "issue_type": IssueType.TASK,
        "priority": Priority.MEDIUM,
        "assignee_name": assignee,
        "labels": ["l1"],
        "links": [],
        "quotes": [],
    }


def test_parse_or_repair_salvages_multiple_tasks_when_one_is_invalid():
    payload = {
        "tasks": [
            _task("Valid 1"),
            _task("Valid 2", assignee=" "),  # invalid assignee string, should be coerced to None
            _task("Valid 3", description=""),  # invalid description, should be skipped
            _task("Valid 4"),
        ]
    }
    raw = json.dumps(payload)

    result = LLMExtractor._parse_or_repair_response(DummyLLM(), raw)

    assert len(result.tasks) == 3
    assert {t.summary for t in result.tasks} == {"Valid 1", "Valid 2", "Valid 4"}
    assert result.tasks[1].assignee_name is None


def test_salvage_returns_none_when_no_valid_tasks():
    raw = json.dumps({"tasks": [{"summary": "x", "description": "", "issue_type": "Task", "priority": "Low"}]})

    salvaged = LLMExtractor._salvage_tasks(raw)

    assert salvaged is None
