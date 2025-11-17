from __future__ import annotations

import types

import pytest

from backend import container


class DummyUseCase:
    async def process_job(self, job) -> None:  # pragma: no cover - helper
        raise NotImplementedError


def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "AZURE_STORAGE_QUEUE_NAME",
        "AZURE_STORAGE_QUEUE_CONNECTION_STRING",
        "AZURE_STORAGE_CONNECTION_STRING",
    ):
        monkeypatch.delenv(key, raising=False)
    container.get_settings.cache_clear()
    container.get_meeting_queue.cache_clear()
    container.get_meeting_queue_worker.cache_clear()
    container.get_extract_use_case.cache_clear()


def test_meeting_queue_worker_none_when_queue_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(container, "get_extract_use_case", lambda: DummyUseCase())

    worker = container.get_meeting_queue_worker()

    assert worker is None


def test_meeting_queue_worker_requires_connection_string(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(container, "get_extract_use_case", lambda: DummyUseCase())
    monkeypatch.setenv("AZURE_STORAGE_QUEUE_NAME", "ingestion")

    worker = container.get_meeting_queue_worker()

    assert worker is None


def test_meeting_queue_worker_instantiated_with_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(container, "get_extract_use_case", lambda: DummyUseCase())
    monkeypatch.setenv("AZURE_STORAGE_QUEUE_NAME", "ingestion")
    monkeypatch.setenv(
        "AZURE_STORAGE_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;"
        "AccountName=testaccount;"
        "AccountKey=dGVzdA==;"
        "EndpointSuffix=core.windows.net",
    )
    fake_client = object()
    monkeypatch.setattr(container, "_ensure_queue_client", lambda *_: fake_client)

    worker = container.get_meeting_queue_worker()

    assert worker is not None
    assert getattr(worker, "_queue_client") is fake_client
