from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from backend.domain.entities import MeetingImportJob
from backend.domain.ports import MeetingImportQueuePort
from backend.mlflow_logging import logger


class BackgroundMeetingImportQueue(MeetingImportQueuePort):
    """In-process asyncio-based queue used for local/POC deployments."""

    def __init__(self, handler: Callable[[MeetingImportJob], Awaitable[None]]) -> None:
        self._handler = handler
        self._queue: asyncio.Queue[MeetingImportJob] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None

    async def enqueue(self, job: MeetingImportJob) -> None:
        await self._queue.put(job)
        if not self._worker_task or self._worker_task.done():
            logger.info("Starting background import worker for meeting %s", job.meeting_id)
            self._worker_task = asyncio.create_task(self._worker())

    async def _worker(self) -> None:
        while True:
            try:
                job = await self._queue.get()
            except asyncio.CancelledError:
                return
            try:
                await self._handler(job)
            except Exception:  # pragma: no cover - best effort logging
                logger.exception("Meeting import job failed", extra={"meeting_id": job.meeting_id})
            finally:
                self._queue.task_done()
