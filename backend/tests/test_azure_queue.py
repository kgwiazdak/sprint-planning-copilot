from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

import pytest

from backend.domain.entities import MeetingImportJob
from backend.infrastructure.queue.azure_storage import AzureMeetingImportQueue, AzureQueueWorker


class StubQueueMessage:
    def __init__(self, *, content: str, message_id: str) -> None:
        self.content = content
        self.id = message_id
        self.pop_receipt = f"pop-{message_id}"


class StubQueueClient:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.deleted: list[tuple[str, str]] = []
        self._pending: list[str] = []

    def send_message(self, payload: str) -> None:
        self.sent.append(payload)
        self._pending.append(payload)

    def receive_messages(self, messages_per_page: int, visibility_timeout: int):
        batch = self._pending[:messages_per_page]
        self._pending = self._pending[messages_per_page:]
        return [StubQueueMessage(content=payload, message_id=str(idx)) for idx, payload in enumerate(batch)]

    def delete_message(self, message_id: str, pop_receipt: str) -> None:
        self.deleted.append((message_id, pop_receipt))


@pytest.mark.asyncio
async def test_azure_queue_serializes_job_payload():
    client = StubQueueClient()
    queue = AzureMeetingImportQueue(queue_client=client)
    job = MeetingImportJob(
        meeting_id="abc",
        title="Daily sync",
        started_at="2024-11-01T10:00:00Z",
        blob_url="https://blob",
        original_filename="sync.txt",
    )

    await queue.enqueue(job)

    assert client.sent
    payload = json.loads(client.sent[0])
    assert payload == asdict(job)


@pytest.mark.asyncio
async def test_azure_queue_worker_processes_payload_and_deletes_message():
    client = StubQueueClient()
    queue = AzureMeetingImportQueue(queue_client=client)
    job = MeetingImportJob(
        meeting_id="job-1",
        title="Planning",
        started_at="2024-11-05T09:00:00Z",
        blob_url="https://blob",
        original_filename=None,
    )
    await queue.enqueue(job)

    processed: list[str] = []

    async def handler(payload: MeetingImportJob) -> None:
        processed.append(payload.meeting_id)

    worker = AzureQueueWorker(
        queue_client=client,
        handler=handler,
        visibility_timeout=5,
        poll_interval_seconds=0.01,
        max_batch_size=2,
    )

    async def _run_worker_once():
        task = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0.05)
        worker.stop()
        await task

    await _run_worker_once()
    assert processed == ["job-1"]
    assert client.deleted, "Message should be deleted after processing"
