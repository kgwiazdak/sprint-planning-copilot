from __future__ import annotations

import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Literal

from backend.application.commands.meeting_import import MeetingImportPayload, SubmitMeetingImportCommand
from backend.application.services.push_to_jira import PushTasksToJiraService
from backend.container import get_mock_audio_path
from backend.domain.ports import MeetingsRepositoryPort
from backend.infrastructure.jira import JiraClient, JiraClientError
from backend.infrastructure.persistence.sqlite import TASK_STATUSES
from backend.infrastructure.storage.blob import BlobStorageConfigError, BlobStorageService
from backend.presentation.http.dependencies import (
    blob_storage_service,
    data_repository,
    jira_client as jira_dependency,
    submit_import_command,
    worker_blob_storage_service,
)
from backend.presentation.http.security import require_authenticated_user
from backend.settings import get_settings

router = APIRouter(
    prefix="/api",
    tags=["ui"],
    dependencies=[Depends(require_authenticated_user)],
)
logger = logging.getLogger(__name__)


class MeetingCreate(BaseModel):
    title: str = Field(..., min_length=3)
    startedAt: str
    sourceUrl: str | None = None
    sourceText: str | None = None


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3)
    startedAt: str | None = None


class TaskUpdate(BaseModel):
    summary: str | None = None
    description: str | None = None
    issueType: str | None = None
    priority: str | None = None
    storyPoints: int | None = None
    assigneeId: str | None = None
    labels: list[str] | None = None
    status: Literal["draft", "approved", "rejected"] | None = None


class BulkAction(BaseModel):
    ids: list[str] = Field(default_factory=list)


class VoiceUploadResponse(BaseModel):
    userId: str
    displayName: str
    voiceSamplePath: str | None = None
    blobUrl: str | None = None


class BlobUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1)
    contentType: str | None = None
    meetingId: str | None = None
    expiresIn: int | None = Field(default=3600, ge=60, le=86400)


class BlobUploadResponse(BaseModel):
    uploadUrl: str
    blobUrl: str
    blobPath: str
    expiresAt: datetime
    meetingId: str


class MeetingImportRequest(BaseModel):
    title: str = Field(..., min_length=3)
    startedAt: str
    blobUrl: str = Field(..., min_length=1)
    originalFilename: str | None = None
    meetingId: str | None = None


def _repo(repo: MeetingsRepositoryPort = Depends(data_repository)) -> MeetingsRepositoryPort:
    return repo


@router.get("/meetings")
def list_meetings(repo: MeetingsRepositoryPort = Depends(_repo)):
    return repo.list_meetings()


@router.post("/meetings", status_code=201)
def create_meeting(payload: MeetingCreate, repo: MeetingsRepositoryPort = Depends(_repo)):
    return repo.create_meeting(
        title=payload.title,
        started_at=payload.startedAt,
        source_url=payload.sourceUrl,
        source_text=payload.sourceText,
    )


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: str, repo: MeetingsRepositoryPort = Depends(_repo)):
    meeting = repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.patch("/meetings/{meeting_id}")
def update_meeting(meeting_id: str, payload: MeetingUpdate, repo: MeetingsRepositoryPort = Depends(_repo)):
    try:
        return repo.update_meeting(
            meeting_id,
            title=payload.title,
            started_at=payload.startedAt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: str, repo: MeetingsRepositoryPort = Depends(_repo)):
    deleted = repo.delete_meeting(meeting_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meeting not found")


@router.get("/meetings/{meeting_id}/tasks")
def list_meeting_tasks(meeting_id: str, repo: MeetingsRepositoryPort = Depends(_repo)):
    meeting = repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return repo.list_tasks(meeting_id=meeting_id)


@router.get("/tasks")
def list_tasks(
        status: str | None = Query(default=None),
        repo: MeetingsRepositoryPort = Depends(_repo),
):
    if status and status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status filter")
    return repo.list_tasks(status=status)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, repo: MeetingsRepositoryPort = Depends(_repo)):
    task = repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, payload: TaskUpdate, repo: MeetingsRepositoryPort = Depends(_repo)):
    try:
        return repo.update_task(task_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/bulk-approve")
def bulk_approve_tasks(
        payload: BulkAction,
        repo: MeetingsRepositoryPort = Depends(_repo),
        jira: JiraClient = Depends(jira_dependency),
):
    service = PushTasksToJiraService(repo=repo, jira_client=jira)
    try:
        result = service.push(payload.ids)
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"updated": result.pushed, "pushed": result.pushed, "skipped": result.skipped}


@router.post("/tasks/bulk-reject")
def bulk_reject_tasks(payload: BulkAction, repo: MeetingsRepositoryPort = Depends(_repo)):
    repo.bulk_update_status(payload.ids, "rejected")
    return {"updated": len(payload.ids)}


@router.get("/users")
def list_users(repo: MeetingsRepositoryPort = Depends(_repo)):
    return repo.list_users()


@router.post("/users/voice", response_model=VoiceUploadResponse, status_code=201)
async def upload_voice_sample(
        displayName: str = Form(..., min_length=1),
        file: UploadFile = File(...),
        userId: str | None = Form(default=None),
        repo: MeetingsRepositoryPort = Depends(_repo),
        worker_storage: BlobStorageService = Depends(worker_blob_storage_service),
):
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Audio file is empty.")
    slug = _slugify_name(displayName)
    ext = Path(file.filename or "").suffix.lower()
    if not ext or len(ext) > 5:
        ext = ".mp3"
    filename = f"intro_{slug}{ext}"
    voices_dir = Path(os.getenv("INTRO_AUDIO_DIR", "data/voices"))
    voices_dir.mkdir(parents=True, exist_ok=True)
    local_path = voices_dir / filename
    local_path.write_bytes(payload)
    blob_url = await worker_storage.upload_blob(
        blob_name=filename,
        content=payload,
        content_type=file.content_type or "audio/mpeg",
    )
    try:
        if userId:
            repo.update_user_voice_sample(userId, displayName, str(local_path))
            final_user_id = userId
        else:
            final_user_id = repo.register_voice_profile(display_name=displayName, voice_sample_path=str(local_path))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    user = repo.get_user(final_user_id)
    return VoiceUploadResponse(
        userId=final_user_id,
        displayName=user["displayName"] if user else displayName,
        voiceSamplePath=str(local_path),
        blobUrl=blob_url,
    )


@router.get("/mock/audio")
def download_mock_audio():
    settings = get_settings()
    if not settings.mock_audio.enabled:
        raise HTTPException(status_code=404, detail="Mock audio disabled.")
    path = get_mock_audio_path()
    if not path or not path.exists():
        raise HTTPException(status_code=503, detail="Mock audio unavailable.")
    return FileResponse(path, filename=path.name, media_type="audio/mpeg")


@router.post("/uploads/blob", response_model=BlobUploadResponse)
def create_blob_upload(
        payload: BlobUploadRequest,
        storage: BlobStorageService = Depends(blob_storage_service),
):
    meeting_id = payload.meetingId or str(uuid.uuid4())
    try:
        token = storage.generate_upload_token(
            meeting_id=meeting_id,
            original_filename=payload.filename,
            content_type=payload.contentType,
            expires_in_seconds=payload.expiresIn or 3600,
        )
    except (BlobStorageConfigError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return BlobUploadResponse(
        uploadUrl=token.upload_url,
        blobUrl=token.blob_url,
        blobPath=token.blob_path,
        expiresAt=token.expires_at,
        meetingId=meeting_id,
    )


@router.post("/meetings/import", status_code=202)
async def import_meeting(
        payload: MeetingImportRequest,
        command: SubmitMeetingImportCommand = Depends(submit_import_command),
):
    meeting_id = await command.execute(
        MeetingImportPayload(
            title=payload.title,
            started_at=payload.startedAt,
            blob_url=payload.blobUrl,
            original_filename=payload.originalFilename,
            meeting_id=payload.meetingId,
        )
    )
    return {"meetingId": meeting_id, "status": "queued"}


def _slugify_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().lower()
    slug = re.sub(r"[^\w]+", "_", normalized, flags=re.UNICODE)
    slug = slug.strip("_")
    return slug or "speaker"
