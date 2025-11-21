from __future__ import annotations

import asyncio
import asyncio
import pytest
from dataclasses import dataclass

from backend.application.commands.meeting_import import MeetingImportPayload, SubmitMeetingImportCommand
from backend.domain.entities import MeetingImportJob


@dataclass
class StubRepo:
    stub_calls: list[tuple[str, str, str, str]] | None = None
    status: tuple[str, str] | None = None

    def create_meeting_stub(self, *, meeting_id: str, title: str, started_at: str, blob_url: str) -> None:
        self.stub_calls = [(meeting_id, title, started_at, blob_url)]

    def update_meeting_status(self, meeting_id: str, status: str) -> None:
        self.status = (meeting_id, status)


class StubQueue:
    def __init__(self) -> None:
        self.jobs: list[MeetingImportJob] = []

    async def enqueue(self, job: MeetingImportJob) -> None:
        self.jobs.append(job)


def test_submit_meeting_import_command_enqueues_job():
    asyncio.run(_run_submit_command())


async def _run_submit_command():
    repo = StubRepo()
    queue = StubQueue()
    command = SubmitMeetingImportCommand(repository=repo, queue=queue)

    meeting_id = await command.execute(
        MeetingImportPayload(
            title="Demo",
            started_at="2024-10-05T10:00:00Z",
            blob_url="https://blob/url",
            meeting_id="abc",
            original_filename="demo.mp3",
        )
    )

    assert meeting_id == "abc"
    assert repo.stub_calls == [("abc", "Demo", "2024-10-05T10:00:00Z", "https://blob/url")]
    assert queue.jobs and queue.jobs[0].meeting_id == "abc"
