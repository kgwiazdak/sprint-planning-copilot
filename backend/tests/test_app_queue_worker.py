from __future__ import annotations

import asyncio
import os

import backend.app as backend_app_module
from backend.app import app as fastapi_app
from fastapi.testclient import TestClient


class DummyWorker:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = False
        self._stop_event: asyncio.Event | None = None

    async def run_forever(self) -> None:
        self.started += 1
        self._stop_event = asyncio.Event()
        await self._stop_event.wait()

    def stop(self) -> None:
        self.stopped = True
        if self._stop_event and not self._stop_event.is_set():
            self._stop_event.set()


def test_queue_worker_background_task(monkeypatch):
    worker = DummyWorker()
    monkeypatch.setattr(backend_app_module, "get_meeting_queue_worker", lambda: worker)
    with TestClient(fastapi_app):
        pass
    os.environ.pop("APP_PROFILE", None)
    assert worker.started == 1
    assert worker.stopped
