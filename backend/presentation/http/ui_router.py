from __future__ import annotations

import uuid
from datetime import datetime
import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.application.use_cases.extract_meeting import ExtractMeetingUseCase
from backend.infrastructure.persistence.sqlite import SqliteMeetingsRepository, TASK_STATUSES
from backend.infrastructure.storage.blob import BlobStorageConfigError, BlobStorageService
from backend.presentation.http.dependencies import blob_storage_service, data_repository, extraction_workflow

router = APIRouter(prefix="/api", tags=["ui"])
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


def _repo(repo: SqliteMeetingsRepository = Depends(data_repository)) -> SqliteMeetingsRepository:
    return repo


@router.get("/meetings")
def list_meetings(repo: SqliteMeetingsRepository = Depends(_repo)):
    return repo.list_meetings()


@router.post("/meetings", status_code=201)
def create_meeting(payload: MeetingCreate, repo: SqliteMeetingsRepository = Depends(_repo)):
    return repo.create_meeting(
        title=payload.title,
        started_at=payload.startedAt,
        source_url=payload.sourceUrl,
        source_text=payload.sourceText,
    )


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: str, repo: SqliteMeetingsRepository = Depends(_repo)):
    meeting = repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.patch("/meetings/{meeting_id}")
def update_meeting(meeting_id: str, payload: MeetingUpdate, repo: SqliteMeetingsRepository = Depends(_repo)):
    try:
        return repo.update_meeting(
            meeting_id,
            title=payload.title,
            started_at=payload.startedAt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: str, repo: SqliteMeetingsRepository = Depends(_repo)):
    deleted = repo.delete_meeting(meeting_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meeting not found")


@router.get("/meetings/{meeting_id}/tasks")
def list_meeting_tasks(meeting_id: str, repo: SqliteMeetingsRepository = Depends(_repo)):
    meeting = repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return repo.list_tasks(meeting_id=meeting_id)


@router.get("/tasks")
def list_tasks(
    status: str | None = Query(default=None),
    repo: SqliteMeetingsRepository = Depends(_repo),
):
    if status and status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status filter")
    return repo.list_tasks(status=status)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, repo: SqliteMeetingsRepository = Depends(_repo)):
    task = repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, payload: TaskUpdate, repo: SqliteMeetingsRepository = Depends(_repo)):
    try:
        return repo.update_task(task_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/bulk-approve")
def bulk_approve_tasks(payload: BulkAction, repo: SqliteMeetingsRepository = Depends(_repo)):
    repo.bulk_update_status(payload.ids, "approved")
    return {"updated": len(payload.ids)}


@router.post("/tasks/bulk-reject")
def bulk_reject_tasks(payload: BulkAction, repo: SqliteMeetingsRepository = Depends(_repo)):
    repo.bulk_update_status(payload.ids, "rejected")
    return {"updated": len(payload.ids)}


@router.get("/users")
def list_users(repo: SqliteMeetingsRepository = Depends(_repo)):
    return repo.list_users()


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
    workflow: ExtractMeetingUseCase = Depends(extraction_workflow),
):
    meeting_id = payload.meetingId or str(uuid.uuid4())

    async def _run() -> None:
        try:
            await workflow(
                title=payload.title,
                started_at=payload.startedAt,
                blob_url=payload.blobUrl,
                original_filename=payload.originalFilename,
                meeting_id=meeting_id,
            )
        except Exception:
            logger.exception("Asynchronous meeting import failed", extra={"meeting_id": meeting_id})

    asyncio.create_task(_run())
    return {"meetingId": meeting_id, "status": "queued"}
