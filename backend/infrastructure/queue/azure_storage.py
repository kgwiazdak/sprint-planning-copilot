from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from azure.core.exceptions import ResourceExistsError
from azure.storage.queue import QueueClient, QueueServiceClient

from backend.domain.entities import MeetingImportJob
from backend.domain.ports import MeetingImportQueuePort

logger = logging.getLogger(__name__)


def _ensure_queue_client(connection_string: str, queue_name: str) -> QueueClient:
    service_client = QueueServiceClient.from_connection_string(connection_string)
    client = service_client.get_queue_client(queue_name)
    try:
        client.create_queue()
        logger.info("Created Azure Storage queue '%s'", queue_name)
    except ResourceExistsError:
        logger.debug("Azure Storage queue '%s' already exists", queue_name)
    return client


class AzureMeetingImportQueue(MeetingImportQueuePort):
    """Azure Storage Queue implementation for meeting import jobs."""

    def __init__(
        self,
        *,
        connection_string: str | None = None,
        queue_name: str | None = None,
        queue_client: QueueClient | None = None,
    ) -> None:
        if queue_client is None:
            if not connection_string or not queue_name:
                raise RuntimeError("Azure queue is not configured.")
            queue_client = _ensure_queue_client(connection_string, queue_name)
        self._queue_client = queue_client

    @property
    def queue_client(self) -> QueueClient:
        return self._queue_client

    async def enqueue(self, job: MeetingImportJob) -> None:
        payload = json.dumps(asdict(job))

        def _send_message() -> None:
            self._queue_client.send_message(payload)

        await asyncio.to_thread(_send_message)
        logger.info("Enqueued meeting import job %s into Azure queue", job.meeting_id)


class AzureQueueWorker:
    """Background worker that polls the Azure Storage queue and processes jobs."""

    def __init__(
        self,
        queue_client: QueueClient,
        handler: Callable[[MeetingImportJob], Awaitable[None]],
        *,
        visibility_timeout: int = 300,
        poll_interval_seconds: float = 2.0,
        max_batch_size: int = 16,
    ) -> None:
        self._queue_client = queue_client
        self._handler = handler
        self._visibility_timeout = visibility_timeout
        self._poll_interval = poll_interval_seconds
        self._max_batch_size = max_batch_size
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        while self._running:
            messages = await asyncio.to_thread(
                lambda: list(
                    self._queue_client.receive_messages(
                        messages_per_page=self._max_batch_size,
                        visibility_timeout=self._visibility_timeout,
                    )
                )
            )
            if not messages:
                await asyncio.sleep(self._poll_interval)
                continue
            for message in messages:
                await self._process_message(message)

    async def _process_message(self, message: Any) -> None:
        try:
            job_data = json.loads(message.content)
            job = MeetingImportJob(**job_data)
        except Exception:  # pragma: no cover - safety net
            logger.exception("Invalid queue payload; deleting message")
            await asyncio.to_thread(self._queue_client.delete_message, message.id, message.pop_receipt)
            return

        try:
            await self._handler(job)
        except Exception:
            logger.exception("Meeting import job failed for %s; message will become visible again", job.meeting_id)
        else:
            await asyncio.to_thread(self._queue_client.delete_message, message.id, message.pop_receipt)
            logger.info("Processed and deleted job %s from queue", job.meeting_id)

    def stop(self) -> None:
        self._running = False


__all__ = ["AzureMeetingImportQueue", "AzureQueueWorker", "_ensure_queue_client"]
