import asyncio
import contextlib

import pytest

from backend.domain.entities import MeetingImportJob
from backend.infrastructure.queue.background import BackgroundMeetingImportQueue


@pytest.mark.asyncio
async def test_background_queue_keeps_worker_alive_for_new_jobs():
    processed: list[str] = []

    async def handler(job: MeetingImportJob) -> None:
        processed.append(job.meeting_id)

    queue = BackgroundMeetingImportQueue(handler)
    first = MeetingImportJob(
        meeting_id="job-1",
        title="Test meeting 1",
        started_at="2024-01-01T00:00:00Z",
        blob_url="https://example.com/blob1",
        owner_id="alice",
    )
    second = MeetingImportJob(
        meeting_id="job-2",
        title="Test meeting 2",
        started_at="2024-01-02T00:00:00Z",
        blob_url="https://example.com/blob2",
        owner_id="alice",
    )

    await queue.enqueue(first)
    await asyncio.wait_for(queue._queue.join(), timeout=1)

    assert queue._worker_task is not None
    assert not queue._worker_task.done()

    await queue.enqueue(second)
    await asyncio.wait_for(queue._queue.join(), timeout=1)

    assert processed == ["job-1", "job-2"]

    if queue._worker_task:
        queue._worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await queue._worker_task
