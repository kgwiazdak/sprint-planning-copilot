from __future__ import annotations

import json
import logging
import urllib.request

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


def _fetch_jira_resource_from_atlassian(token: str) -> dict | None:
    req = urllib.request.Request(
        "https://api.atlassian.com/oauth/token/accessible-resources",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = resp.read().decode("utf-8") or "[]"
    resources = json.loads(payload)
    if not isinstance(resources, list) or not resources:
        return None
    jira_resources = [r for r in resources if any("jira" in s for s in r.get("scopes", []))]
    if not jira_resources:
        jira_resources = resources
    return jira_resources[0] if jira_resources else None


def jira_client(user: AuthenticatedUser = Depends(require_authenticated_user)) -> JiraClient:
    # Prefer the Atlassian OAuth token from the current user if available.
    if user.access_token:
        try:
            resource = _fetch_jira_resource_from_atlassian(user.access_token)
            if resource:
                cloud_id = resource.get("id")
                api_base = f"https://api.atlassian.com/ex/jira/{cloud_id}" if cloud_id else None
                base_url = api_base or resource.get("url")
                if not base_url:
                    raise ValueError("Atlassian resource did not include an id or url.")
                return JiraClient(
                    base_url=base_url,
                    api_token=None,
                    email=None,
                    bearer_token=user.access_token,
                )
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Falling back to static Jira client; Atlassian token flow failed: %s", exc
            )
    client = get_jira_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Jira integration is not configured.")
    return client
