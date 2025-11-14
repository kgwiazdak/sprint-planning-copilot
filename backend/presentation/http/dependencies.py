from __future__ import annotations

from backend.application.use_cases.extract_meeting import ExtractMeetingUseCase
from backend.infrastructure.persistence.sqlite import SqliteMeetingsRepository
from backend.container import get_extract_use_case, get_meetings_repository


def extraction_workflow() -> ExtractMeetingUseCase:
    return get_extract_use_case()


def data_repository() -> SqliteMeetingsRepository:
    return get_meetings_repository()
