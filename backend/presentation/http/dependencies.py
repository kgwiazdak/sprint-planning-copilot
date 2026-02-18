from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from fastapi import Depends, HTTPException

from backend.application.commands.meeting_import import SubmitMeetingImportCommand
from backend.application.use_cases.extract_meeting import ExtractMeetingUseCase
from backend.container import (
    get_blob_storage,
    get_worker_blob_storage,
    get_extract_use_case,
    get_jira_client,
    get_meeting_queue,
    get_meetings_repository,
)
from backend.domain.ports import MeetingImportQueuePort, MeetingsRepositoryPort
from backend.infrastructure.jira import JiraClient
from backend.infrastructure.storage.blob import BlobStorageService
from backend.presentation.http.security import AuthenticatedUser, require_authenticated_user
from backend.settings import get_settings


def extraction_workflow() -> ExtractMeetingUseCase:
    return get_extract_use_case()


def data_repository() -> MeetingsRepositoryPort:
    return get_meetings_repository()


def blob_storage_service() -> BlobStorageService:
    storage = get_blob_storage()
    if storage is None:
        raise RuntimeError("Blob storage is not configured.")
    return storage


def worker_blob_storage_service() -> BlobStorageService:
    storage = get_worker_blob_storage()
    if storage is None:
        raise RuntimeError("Worker blob storage is not configured.")
    return storage


def meeting_queue() -> MeetingImportQueuePort:
    return get_meeting_queue()


def submit_import_command() -> SubmitMeetingImportCommand:
    return SubmitMeetingImportCommand(repository=get_meetings_repository(), queue=get_meeting_queue())


def _oauth_jira_client(user: AuthenticatedUser) -> JiraClient | None:
    token = (user.access_token or "").strip()
    if not token:
        return None

    req = urllib.request.Request(
        "https://api.atlassian.com/oauth/token/accessible-resources",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resources = json.loads(resp.read().decode("utf-8") or "[]")
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return None

    if not isinstance(resources, list) or not resources:
        return None

    cfg = get_settings().jira
    preferred_host = urlparse((cfg.base_url or "").strip()).hostname
    selected = None
    for row in resources:
        if not isinstance(row, dict):
            continue
        if preferred_host and urlparse(str(row.get("url") or "")).hostname == preferred_host:
            selected = row
            break
    if selected is None:
        selected = next((row for row in resources if isinstance(row, dict)), None)
    if not isinstance(selected, dict):
        return None

    cloud_id = str(selected.get("id") or "").strip()
    if not cloud_id:
        return None
    browse_url = str(selected.get("url") or cfg.base_url or "").strip() or None
    try:
        return JiraClient(
            base_url=f"https://api.atlassian.com/ex/jira/{cloud_id}",
            browse_base_url=browse_url,
            bearer_token=token,
            project_key=cfg.project_key,
            story_points_field=cfg.story_points_field,
        )
    except ValueError:
        return None


def jira_client(user: AuthenticatedUser = Depends(require_authenticated_user)):
    oauth_client = _oauth_jira_client(user)
    if oauth_client is not None:
        return oauth_client

    client = get_jira_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Jira integration is not configured.")
    return client
