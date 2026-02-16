from __future__ import annotations

from backend.infrastructure.llm.task_extractor import LLMExtractor
from backend.schemas import ExtractionResult, IssueType, Priority, Task


def _task(summary: str, assignee: str | None = "Alice", points: int | None = 3) -> Task:
    return Task(
        summary=summary,
        description="desc",
        issue_type=IssueType.TASK,
        priority=Priority.MEDIUM,
        assignee_name=assignee,
        story_points=points,
        labels=[],
        links=[],
        quotes=[],
    )


def test_policy_adds_low_confidence_labels():
    extractor = LLMExtractor()
    result = ExtractionResult(tasks=[_task("Task A")])
    report = {
        "overall_confidence": 0.52,
        "tasks": [
            {
                "summary": "Task A",
                "overall": 0.52,
                "speaker": 0.4,
                "points": 0.6,
                "rationale": "weak evidence",
            }
        ],
        "low_confidence_tasks": 1,
    }

    updated = extractor._apply_confidence_policy(result=result, report=report, force_human_review=False)

    labels = updated.tasks[0].labels
    assert "needs-human-review" in labels
    assert "low-confidence-speaker" in labels
    assert "low-confidence-story-points" in labels


def test_policy_forced_human_review_marks_every_task():
    extractor = LLMExtractor()
    result = ExtractionResult(tasks=[_task("Task B", assignee=None)])
    report = {
        "overall_confidence": 0.91,
        "tasks": [
            {
                "summary": "Task B",
                "overall": 0.91,
                "speaker": 0.95,
                "points": 0.95,
                "rationale": "strong evidence",
            }
        ],
        "low_confidence_tasks": 0,
    }

    updated = extractor._apply_confidence_policy(result=result, report=report, force_human_review=True)

    assert "needs-human-review" in updated.tasks[0].labels
