from __future__ import annotations

import contextlib
import types

from fastapi.testclient import TestClient

import backend.app as backend_app_module
from backend.app import app as fastapi_app
from backend.domain.status import MeetingStatus
from backend.presentation.http.dependencies import data_repository, meeting_queue
from backend.presentation.http.security import AuthenticatedUser, require_authenticated_user


class StubMeetingsRepository:
    def __init__(self, meetings: list[dict[str, str]]):
        self._meetings = meetings

    def list_meetings(self, *, owner_id: str) -> list[dict[str, str]]:
        assert owner_id == "owner-queue-status"
        return self._meetings


class DummyQueueClient:
    def __init__(self, message_count: int = 0, fail: bool = False):
        self._message_count = message_count
        self._fail = fail

    def get_queue_properties(self):
        if self._fail:
            raise RuntimeError("queue unreachable")
        return types.SimpleNamespace(approximate_message_count=self._message_count)


class StubAzureQueue:
    def __init__(self, message_count: int = 0, fail: bool = False):
        self._client = DummyQueueClient(message_count=message_count, fail=fail)

    async def enqueue(self, job) -> None:  # pragma: no cover - not used in test
        raise NotImplementedError

    @property
    def queue_client(self) -> DummyQueueClient:
        return self._client


class StubInProcessQueue:
    async def enqueue(self, job) -> None:  # pragma: no cover - not used in test
        raise NotImplementedError


@contextlib.contextmanager
def _override_dependencies(repo, queue):
    user = AuthenticatedUser(
        subject="owner-queue-status",
        name="queue checker",
        tenant_id=None,
        roles=[],
        claims={},
    )

    async def _stub_user():
        return user

    fastapi_app.dependency_overrides[data_repository] = lambda: repo
    fastapi_app.dependency_overrides[meeting_queue] = lambda: queue
    fastapi_app.dependency_overrides[require_authenticated_user] = _stub_user
    original_worker = backend_app_module.get_meeting_queue_worker
    backend_app_module.get_meeting_queue_worker = lambda: None
    try:
        with TestClient(fastapi_app) as client:
            yield client
    finally:
        backend_app_module.get_meeting_queue_worker = original_worker
        fastapi_app.dependency_overrides.clear()


def test_queue_status_reports_azure_depth():
    repo = StubMeetingsRepository(
        [
            {"status": MeetingStatus.QUEUED.value},
            {"status": MeetingStatus.PROCESSING.value},
        ]
    )
    queue = StubAzureQueue(message_count=5)
    with _override_dependencies(repo, queue) as client:
        response = client.get("/api/queue/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["queuedCount"] == 1
    assert payload["processingCount"] == 1
    assert payload["azureQueue"]["configured"] is True
    assert payload["azureQueue"]["approximateMessageCount"] == 5
    assert payload["stalled"] is False


def test_queue_status_flags_stalled_state():
    repo = StubMeetingsRepository(
        [
            {"status": MeetingStatus.QUEUED.value},
        ]
    )
    queue = StubInProcessQueue()
    with _override_dependencies(repo, queue) as client:
        response = client.get("/api/queue/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["queuedCount"] == 1
    assert payload["processingCount"] == 0
    assert payload["azureQueue"]["configured"] is False
    assert payload["stalled"] is True


def test_queue_status_handles_queue_client_errors():
    repo = StubMeetingsRepository([])
    queue = StubAzureQueue(message_count=0, fail=True)
    with _override_dependencies(repo, queue) as client:
        response = client.get("/api/queue/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["azureQueue"]["configured"] is True
    assert payload["azureQueue"]["error"] is not None
