from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.schemas import ExtractionResult


@runtime_checkable
class BlobStoragePort(Protocol):
    async def save_file(
        self,
        *,
        meeting_id: str,
        original_filename: str,
        content: bytes,
        content_type: str | None,
    ) -> str:
        """Persist the original upload and return a blob URI."""


@runtime_checkable
class TranscriptionPort(Protocol):
    SUPPORTED_AUDIO_EXTENSIONS: tuple[str, ...]

    def transcribe(self, content: bytes, filename: str) -> str:
        """Return a transcript for the provided audio payload."""


@runtime_checkable
class ExtractionPort(Protocol):
    def extract(self, transcript: str) -> ExtractionResult:
        """Convert a transcript to structured tasks."""


@runtime_checkable
class MeetingsRepositoryPort(Protocol):
    def store_meeting_and_result(
        self,
        filename: str,
        transcript: str,
        result_model: ExtractionResult,
        *,
        meeting_id: str | None = None,
    ) -> tuple[str, str]:
        """Persist transcript and extraction payload and return (meeting_id, run_id)."""


@runtime_checkable
class TelemetryPort(Protocol):
    def log_extraction_run(
        self,
        *,
        meeting_id: str,
        run_id: str,
        transcript: str,
        result: ExtractionResult,
        meeting_date: str,
        transcript_blob_uri: str | None,
    ) -> None:
        """Emit telemetry for an extraction workflow."""
