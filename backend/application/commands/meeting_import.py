from __future__ import annotations

import uuid
from dataclasses import dataclass

from backend.domain.entities import MeetingImportJob
from backend.domain.ports import MeetingImportQueuePort, MeetingsRepositoryPort
from backend.domain.status import MeetingStatus


@dataclass(slots=True)
class MeetingImportPayload:
    title: str
    started_at: str
    blob_url: str
    meeting_id: str | None = None
    original_filename: str | None = None


class SubmitMeetingImportCommand:
    """Handles API submission by persisting stub meetings and enqueuing jobs."""

    def __init__(
            self,
            *,
            repository: MeetingsRepositoryPort,
            queue: MeetingImportQueuePort,
    ) -> None:
        self._repo = repository
        self._queue = queue

    async def execute(self, payload: MeetingImportPayload) -> str:
        meeting_id = payload.meeting_id or str(uuid.uuid4())
        self._repo.create_meeting_stub(
            meeting_id=meeting_id,
            title=payload.title,
            started_at=payload.started_at,
            blob_url=payload.blob_url,
        )
        job = MeetingImportJob(
            meeting_id=meeting_id,
            title=payload.title,
            started_at=payload.started_at,
            blob_url=payload.blob_url,
            original_filename=payload.original_filename,
        )
        await self._queue.enqueue(job)
        self._repo.update_meeting_status(meeting_id, MeetingStatus.QUEUED.value)
        return meeting_id
