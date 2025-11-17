from __future__ import annotations

import asyncio
import pytest

from backend.application.use_cases.extract_meeting import ExtractMeetingUseCase
from backend.schemas import ExtractionResult, IssueType, Task


class DummyExtractor:
    def __init__(self, result: ExtractionResult) -> None:
        self._result = result
        self.transcript = None

    def extract(self, transcript: str) -> ExtractionResult:
        self.transcript = transcript
        return self._result


class DummyRepository:
    def __init__(self) -> None:
        self.captured: dict[str, str | None] | None = None
        self.statuses: list[tuple[str, str]] = []

    def create_meeting_stub(self, **kwargs):
        return None

    def update_meeting_status(self, meeting_id: str, status: str) -> None:
        self.statuses.append((meeting_id, status))

    def store_meeting_and_result(
        self,
        filename: str,
        transcript: str,
        result_model: ExtractionResult,
        *,
        meeting_id: str | None = None,
        title: str | None = None,
        started_at: str | None = None,
        blob_url: str | None = None,
    ) -> tuple[str, str]:
        self.captured = {
            "filename": filename,
            "title": title,
            "started_at": started_at,
            "transcript": transcript,
            "meeting_id": meeting_id,
            "tasks": len(result_model.tasks),
            "blob_url": blob_url,
        }
        return meeting_id or "meeting-id", "run-id"


class DummyBlobStorage:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.downloaded: str | None = None

    async def download_blob(self, blob_url: str) -> bytes:
        self.downloaded = blob_url
        return self.payload

    async def save_file(self, **kwargs):
        raise AssertionError("save_file should not be used when blob_url is supplied")


def test_extract_meeting_use_case_persists_custom_metadata():
    asyncio.run(_run_persists_custom_metadata())


async def _run_persists_custom_metadata():
    payload = b"Meeting transcript line"
    result = ExtractionResult(
        tasks=[
            Task(
                summary="Follow up",
                description="Discuss blockers",
                issue_type=IssueType.TASK,
            )
        ]
    )
    extractor = DummyExtractor(result)
    repo = DummyRepository()
    storage = DummyBlobStorage(payload)
    workflow = ExtractMeetingUseCase(
        blob_storage=storage,
        transcription=None,
        extractor=extractor,
        meetings_repo=repo,
        telemetry=None,
    )

    await workflow(
        title="Sprint Planning",
        started_at="2024-10-01T12:00:00Z",
        blob_url="https://storage/meetings/notes.txt",
        original_filename="notes.txt",
        meeting_id="meeting-123",
    )

    assert storage.downloaded == "https://storage/meetings/notes.txt"
    assert repo.captured is not None
    assert repo.captured["title"] == "Sprint Planning"
    assert repo.captured["started_at"] == "2024-10-01T12:00:00Z"
    assert repo.captured["filename"] == "notes.txt"
    assert repo.captured["meeting_id"] == "meeting-123"
    assert repo.statuses[-1] == ("meeting-123", "completed")


def test_extract_meeting_use_case_accepts_blob_reference():
    asyncio.run(_run_accepts_blob_reference())


async def _run_accepts_blob_reference():
    payload = b"Blob based transcript"
    result = ExtractionResult(
        tasks=[
            Task(
                summary="Review data feed",
                description="Validate latest dump",
                issue_type=IssueType.TASK,
            )
        ]
    )
    extractor = DummyExtractor(result)
    repo = DummyRepository()
    storage = DummyBlobStorage(payload)
    workflow = ExtractMeetingUseCase(
        blob_storage=storage,
        transcription=None,
        extractor=extractor,
        meetings_repo=repo,
        telemetry=None,
    )

    await workflow(
        title="Blob Meeting",
        started_at="2024-10-02T09:00:00Z",
        blob_url="https://storage/meetings/blobfile.txt",
        original_filename="blobfile.txt",
    )

    assert storage.downloaded == "https://storage/meetings/blobfile.txt"
    assert repo.captured is not None
    assert repo.captured["title"] == "Blob Meeting"
    assert repo.captured["filename"] == "blobfile.txt"
