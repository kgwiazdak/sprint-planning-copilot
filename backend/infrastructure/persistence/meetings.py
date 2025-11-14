from __future__ import annotations

from backend.application.ports import MeetingsRepositoryPort
from backend.db.storage import SqliteMeetingsRepository
from backend.schemas import ExtractionResult


class SQLiteMeetingsRepository(MeetingsRepositoryPort):
    """Adapter implementing the MeetingsRepositoryPort via sqlite3."""

    def __init__(self, db_url: str | None = None) -> None:
        self._repo = SqliteMeetingsRepository(db_url)

    def store_meeting_and_result(
        self,
        filename: str,
        transcript: str,
        result_model: ExtractionResult,
        *,
        meeting_id: str | None = None,
    ) -> tuple[str, str]:
        return self._repo.store_meeting_and_result(
            filename,
            transcript,
            result_model,
            meeting_id=meeting_id,
        )
