from backend.application.services.rag_estimator import RAGConfig, RAGEstimator
from backend.schemas import Task, ExtractionResult, IssueType, Priority


def test_rag_estimator_keeps_explicit_points_and_estimates_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_RAG", "1")
    config = RAGConfig(persist_dir=tmp_path / "rag-index", confluence_dir=tmp_path / "conf")
    rag = RAGEstimator(config=config)
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
    updated, stats = rag.enrich(
        transcript="We need to add drift alerting and parallelize preprocessing.",
        result=result,
        history_tasks=history,
        meeting_id="m-123",
        project_key="DATA",
    )

    assert updated.tasks[0].story_points == 8  # explicit not overwritten
    assert updated.tasks[1].story_points is not None
    assert "rag-estimated" in updated.tasks[1].labels
    assert "rag-description-enhanced" in updated.tasks[1].labels
    assert updated.tasks[1].description
    assert updated.tasks[1].description != "accuracy drop alert"
    assert stats["story_points_kept"] == 1
    assert stats["story_points_estimated"] == 1
    assert stats["description_enhanced"] >= 1
    assert stats["ingested_history"] == 2
