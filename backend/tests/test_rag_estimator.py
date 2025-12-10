from backend.application.services.rag_estimator import RAGEstimator
from backend.schemas import Task, ExtractionResult, IssueType, Priority


def test_rag_estimator_keeps_explicit_points_and_estimates_missing(tmp_path):
    rag = RAGEstimator(confluence_dir="mock_confluence")
    history = [
        {"id": "T1", "summary": "Parallelize preprocessing with Dask", "description": "fan-out", "storyPoints": 5},
        {"id": "T2", "summary": "Drift detection with Slack", "description": "alert", "storyPoints": 3},
    ]
    tasks = [
        Task(
            summary="Parallelize preprocessing with Dask",
            description="fan-out work",
            issue_type=IssueType.STORY,
            priority=Priority.MEDIUM,
            story_points=8,
        ),
        Task(
            summary="Add drift alert",
            description="accuracy drop alert",
            issue_type=IssueType.STORY,
            priority=Priority.MEDIUM,
            story_points=None,
        ),
    ]
    result = ExtractionResult(tasks=tasks)
    updated, stats = rag.enrich(transcript="", result=result, history_tasks=history)

    assert updated.tasks[0].story_points == 8  # explicit not overwritten
    assert updated.tasks[1].story_points is not None
    assert stats["kept"] == 1
    assert stats["estimated"] == 1
