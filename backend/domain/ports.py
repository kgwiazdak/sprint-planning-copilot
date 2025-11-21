from __future__ import annotations

from typing import Any, Iterable, Protocol, runtime_checkable

from backend.domain.entities import MeetingImportJob
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

    async def download_blob(self, blob_url: str) -> bytes:
        """Retrieve bytes from an existing blob URL."""


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
    def list_meetings(self) -> list[dict[str, Any]]:
        """Return all meetings with draft counts."""

    def create_meeting(
            self,
            *,
            title: str,
            started_at: str,
            source_url: str | None,
            source_text: str | None,
    ) -> dict[str, Any]:
        """Create a manual meeting entry."""

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        """Fetch a single meeting."""

    def update_meeting(self, meeting_id: str, *, title: str | None, started_at: str | None) -> dict[str, Any]:
        """Modify meeting metadata."""

    def delete_meeting(self, meeting_id: str) -> bool:
        """Remove a meeting and its tasks."""

    def list_tasks(self, *, meeting_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        """List tasks optionally filtered by meeting or status."""

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Fetch a single task."""

    def update_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply partial updates to a task."""

    def bulk_update_status(self, ids: Iterable[str], status: str) -> int:
        """Update status for multiple tasks."""

    def get_tasks_by_ids(self, ids: Iterable[str]) -> list[dict[str, Any]]:
        """Return tasks by ID preserving metadata."""

    def mark_task_pushed_to_jira(self, task_id: str, *, issue_key: str, issue_url: str | None) -> None:
        """Record Jira issue linkage."""

    def list_users(self) -> list[dict[str, Any]]:
        """Return known users."""

    def register_voice_profile(self, *, display_name: str, voice_sample_path: str | None = None) -> str:
        """Ensure a speaker profile exists."""

    def update_user_voice_sample(self, user_id: str, display_name: str, voice_sample_path: str) -> str:
        """Update an existing speaker profile with a new sample."""

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        """Fetch user by ID."""

    def update_user_jira_account(self, user_id: str, account_id: str) -> None:
        """Store Jira account linkage."""

    def create_meeting_stub(
            self,
            *,
            meeting_id: str,
            title: str,
            started_at: str,
            blob_url: str,
    ) -> None:
        """Persist an initial queued meeting entry."""

    def update_meeting_status(self, meeting_id: str, status: str) -> None:
        """Update ingestion status for an existing meeting."""

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


@runtime_checkable
class MeetingImportQueuePort(Protocol):
    async def enqueue(self, job: MeetingImportJob) -> None:
        """Submit a meeting import task for background processing."""
