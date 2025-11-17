from __future__ import annotations

from pathlib import Path

from backend.infrastructure.persistence.sqlite import SqliteMeetingsRepository
from backend.schemas import ExtractionResult, IssueType, Priority, Task


def _repo(tmp_path: Path) -> SqliteMeetingsRepository:
    db_path = tmp_path / "app.db"
    return SqliteMeetingsRepository(f"sqlite:///{db_path}")


def test_register_voice_profile_creates_or_updates_user(tmp_path):
    repo = _repo(tmp_path)
    first_id = repo.register_voice_profile(display_name="Adrian Puchacki", voice_sample_path="data/voices/adrian.mp3")
    users = repo.list_users()
    assert len(users) == 1
    assert users[0]["displayName"] == "Adrian Puchacki"
    assert users[0]["voiceSamplePath"] == "data/voices/adrian.mp3"

    second_id = repo.register_voice_profile(display_name="adrian puchacki", voice_sample_path="data/voices/new.mp3")
    assert first_id == second_id
    users = repo.list_users()
    assert users[0]["voiceSamplePath"] == "data/voices/new.mp3"


def test_store_tasks_only_assigns_known_voice(tmp_path):
    repo = _repo(tmp_path)
    repo.register_voice_profile(display_name="Alex Johnson", voice_sample_path="data/voices/alex.mp3")

    result = ExtractionResult(
        tasks=[
            Task(
                summary="Implement auth",
                description="Alex will finish the auth story",
                issue_type=IssueType.STORY,
                assignee_name="Alex Johnson",
                priority=Priority.HIGH,
                story_points=3,
                labels=["auth"],
                links=[],
                quotes=["Alex Johnson: I'll own the auth story."],
            ),
            Task(
                summary="Unknown task",
                description="Somebody needs to handle logging",
                issue_type=IssueType.TASK,
                assignee_name="Mystery Speaker",
                priority=Priority.MEDIUM,
                story_points=2,
                labels=[],
                links=[],
                quotes=[],
            ),
        ]
    )

    repo.store_meeting_and_result(
        filename="meeting.mp3",
        transcript="Sample transcript",
        result_model=result,
        meeting_id="meeting-1",
        title="Weekly sync",
        started_at="2024-01-01T00:00:00Z",
        blob_url="https://blob",
    )

    tasks = repo.list_tasks(meeting_id="meeting-1")
    assert len(tasks) == 2
    assigned = {task["summary"]: task["assigneeId"] for task in tasks}
    assert assigned["Implement auth"] is not None
    assert assigned["Unknown task"] is None


def test_update_user_voice_sample(tmp_path):
    repo = _repo(tmp_path)
    user_id = repo.register_voice_profile(display_name="Carla Ruiz", voice_sample_path="data/voices/carla.mp3")
    repo.update_user_voice_sample(user_id, "Carla Ruiz", "data/voices/carla_new.mp3")
    users = repo.list_users()
    assert users[0]["voiceSamplePath"] == "data/voices/carla_new.mp3"
