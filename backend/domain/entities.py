from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MeetingImportJob:
    meeting_id: str
    title: str
    started_at: str
    blob_url: str
    owner_id: str
    project_key: str | None = None
    original_filename: str | None = None
    atlassian_access_token: str | None = None
