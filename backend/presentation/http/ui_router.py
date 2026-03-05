from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
import uuid
import urllib.error
import urllib.request
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Annotated, Any, Literal

from backend.application.commands.meeting_import import MeetingImportPayload, SubmitMeetingImportCommand
from backend.application.services.push_to_jira import PushTasksToJiraService
from backend.container import get_mock_audio_path, get_jira_client
from backend.domain.ports import MeetingImportQueuePort, MeetingsRepositoryPort
from backend.domain.status import MeetingStatus
from backend.infrastructure.jira import JiraClientError
from backend.infrastructure.persistence.sqlite import TASK_STATUSES
from backend.infrastructure.storage.blob import BlobStorageConfigError, BlobStorageService
from backend.infrastructure.storage.local import LocalStorageError
from backend.presentation.http.dependencies import (
    data_repository,
    jira_client as jira_dependency,
    meeting_queue,
    optional_blob_storage_service,
    optional_worker_blob_storage_service,
    submit_import_command,
)
from backend.presentation.http.security import AuthenticatedUser, require_authenticated_user
from backend.settings import get_settings

router = APIRouter(
    prefix="/api",
    tags=["ui"],
)
public_router = APIRouter(
    prefix="/api/auth",
    tags=["auth"],
)
logger = logging.getLogger(__name__)

CurrentUser = Annotated[AuthenticatedUser, Depends(require_authenticated_user)]


class MeetingCreate(BaseModel):
    title: str = Field(..., min_length=3)
    startedAt: str
    sourceUrl: str | None = None
    sourceText: str | None = None
    projectKey: str = Field(..., min_length=1)


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3)
    startedAt: str | None = None
    projectKey: str | None = Field(default=None, min_length=1)


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


class BulkApproveRequest(BulkAction):
    projectKey: str | None = Field(default=None, min_length=1)


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


class AtlassianTokenExchange(BaseModel):
    code: str | None = None
    codeVerifier: str | None = None
    redirectUri: str | None = None
    grantType: Literal["authorization_code", "refresh_token"] = "authorization_code"
    refreshToken: str | None = None


class JiraProjectResponse(BaseModel):
    key: str
    name: str


def _post_json(url: str, payload: dict, *, timeout: float = 15.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") or exc.reason or f"HTTP {exc.code}"
        code = exc.code if 400 <= exc.code < 500 else 502
        raise HTTPException(status_code=code, detail=detail)
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Atlassian: {exc.reason}") from exc


@public_router.post("/atlassian/token")
def exchange_atlassian_token(payload: AtlassianTokenExchange):
    settings = get_settings().atlassian_oauth
    if not settings.client_id or not settings.client_secret:
        raise HTTPException(status_code=503, detail="Atlassian OAuth client is not configured.")

    if payload.grantType == "authorization_code":
        if not payload.code or not payload.codeVerifier:
            raise HTTPException(status_code=400, detail="code and codeVerifier are required.")
        redirect_uri = payload.redirectUri or settings.redirect_uri
        if not redirect_uri:
            raise HTTPException(status_code=400, detail="redirectUri is required.")
        token_payload = {
            "grant_type": "authorization_code",
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "code": payload.code,
            "code_verifier": payload.codeVerifier,
            "redirect_uri": redirect_uri,
        }
    else:
        if not payload.refreshToken:
            raise HTTPException(status_code=400, detail="refreshToken is required for refresh_token grant.")
        token_payload = {
            "grant_type": "refresh_token",
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "refresh_token": payload.refreshToken,
        }

    token_response = _post_json("https://auth.atlassian.com/oauth/token", token_payload)
    return token_response


class AtlassianConfigResponse(BaseModel):
    clientId: str | None = None
    redirectUri: str | None = None
    scopes: list[str] = []


@public_router.get("/atlassian/config", response_model=AtlassianConfigResponse)
def atlassian_config():
    settings = get_settings().atlassian_oauth
    raw_scopes = os.getenv("ATLASSIAN_SCOPES") or os.getenv("VITE_ATLASSIAN_SCOPES") or ""
    scopes = [scope.strip() for scope in re.split(r"[,\s]+", raw_scopes) if scope.strip()]
    return AtlassianConfigResponse(
        clientId=settings.client_id,
        redirectUri=settings.redirect_uri,
        scopes=scopes,
    )


class BlobUploadResponse(BaseModel):
    uploadUrl: str
    blobUrl: str
    blobPath: str
    expiresAt: datetime
    meetingId: str


class LocalUploadResponse(BaseModel):
    blobUrl: str
    blobPath: str
    meetingId: str


class MeetingImportRequest(BaseModel):
    title: str = Field(..., min_length=3)
    startedAt: str
    blobUrl: str = Field(..., min_length=1)
    originalFilename: str | None = None
    meetingId: str | None = None
    projectKey: str = Field(..., min_length=1)


class QueueStats(BaseModel):
    configured: bool = False
    approximateMessageCount: int | None = None
    error: str | None = None


class QueueHealthResponse(BaseModel):
    processingCount: int
    queuedCount: int
    azureQueue: QueueStats
    stalled: bool


class RuntimeConfigResponse(BaseModel):
    ingestBackend: Literal["azure", "local"]


class IngestHealthResponse(BaseModel):
    ingestBackend: Literal["azure", "local"]
    localUploadEnabled: bool
    sasUploadEnabled: bool
    azureQueueEnabled: bool


def _repo(repo: MeetingsRepositoryPort = Depends(data_repository)) -> MeetingsRepositoryPort:
    return repo


async def _delete_meeting_source_asset(source_url: str | None, storage: Any) -> None:
    if not source_url:
        return
    if source_url.startswith("local://"):
        root = Path(get_settings().ingest.local_storage_root) / "uploads"
        rel = source_url[len("local://"):].replace("\\", "/").lstrip("/")
        if not rel:
            return
        target = root / rel
        if target.exists():
            try:
                target.unlink()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to delete local source file '%s': %s", target, exc)
        return
    if storage is None or not hasattr(storage, "delete_blob"):
        return
    try:
        await storage.delete_blob(source_url)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to delete source blob '%s': %s", source_url, exc)


def _count_meeting_statuses(meetings: list[dict[str, Any]]) -> tuple[int, int]:
    queued = 0
    processing = 0
    for meeting in meetings:
        status = meeting.get("status")
        if status == MeetingStatus.QUEUED.value:
            queued += 1
        elif status == MeetingStatus.PROCESSING.value:
            processing += 1
    return queued, processing


@router.get("/queue/status", response_model=QueueHealthResponse)
def queue_status(
        user: CurrentUser,
        repo: MeetingsRepositoryPort = Depends(_repo),
        queue_port: MeetingImportQueuePort = Depends(meeting_queue),
):
    meetings = repo.list_meetings(owner_id=user.subject)
    queued_count, processing_count = _count_meeting_statuses(meetings)
    queue_client = getattr(queue_port, "queue_client", None)
    approximate_message_count: int | None = None
    queue_error: str | None = None
    azure_configured = False
    if queue_client:
        azure_configured = True
        try:
            props = queue_client.get_queue_properties()
            approximate_message_count = int(getattr(props, "approximate_message_count", 0) or 0)
        except Exception as exc:  # pragma: no cover - best effort logging
            logger.warning("Failed to read Azure queue properties: %s", exc)
            queue_error = str(exc)
    azure_stats = QueueStats(
        configured=azure_configured,
        approximateMessageCount=approximate_message_count,
        error=queue_error,
    )
    stalled = queued_count > 0 and processing_count == 0
    return QueueHealthResponse(
        processingCount=processing_count,
        queuedCount=queued_count,
        azureQueue=azure_stats,
        stalled=stalled,
    )


@router.get("/runtime/config", response_model=RuntimeConfigResponse)
def runtime_config(_user: CurrentUser):
    backend = (get_settings().ingest.backend or "azure").strip().lower()
    ingest_backend = "local" if backend == "local" else "azure"
    return RuntimeConfigResponse(ingestBackend=ingest_backend)


@router.get("/ingest/health", response_model=IngestHealthResponse)
def ingest_health(_user: CurrentUser, queue_port: MeetingImportQueuePort = Depends(meeting_queue)):
    backend = (get_settings().ingest.backend or "azure").strip().lower()
    ingest_backend: Literal["azure", "local"] = "local" if backend == "local" else "azure"
    return IngestHealthResponse(
        ingestBackend=ingest_backend,
        localUploadEnabled=ingest_backend == "local",
        sasUploadEnabled=ingest_backend == "azure",
        azureQueueEnabled=hasattr(queue_port, "queue_client"),
    )


@router.get("/meetings")
def list_meetings(user: CurrentUser, repo: MeetingsRepositoryPort = Depends(_repo)):
    return repo.list_meetings(owner_id=user.subject)


@router.post("/meetings", status_code=201)
def create_meeting(payload: MeetingCreate, user: CurrentUser, repo: MeetingsRepositoryPort = Depends(_repo)):
    return repo.create_meeting(
        title=payload.title,
        started_at=payload.startedAt,
        source_url=payload.sourceUrl,
        source_text=payload.sourceText,
        project_key=payload.projectKey,
        owner_id=user.subject,
    )


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: str, user: CurrentUser, repo: MeetingsRepositoryPort = Depends(_repo)):
    meeting = repo.get_meeting(meeting_id, owner_id=user.subject)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.patch("/meetings/{meeting_id}")
def update_meeting(
        meeting_id: str, payload: MeetingUpdate, user: CurrentUser, repo: MeetingsRepositoryPort = Depends(_repo)
):
    try:
        return repo.update_meeting(
            meeting_id,
            title=payload.title,
            started_at=payload.startedAt,
            project_key=payload.projectKey,
            owner_id=user.subject,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/meetings/{meeting_id}", status_code=204)
async def delete_meeting(
        meeting_id: str,
        user: CurrentUser,
        repo: MeetingsRepositoryPort = Depends(_repo),
        storage: Any = Depends(optional_blob_storage_service),
):
    meeting = repo.get_meeting(meeting_id, owner_id=user.subject)
    source_url = meeting.get("sourceUrl") if meeting else None
    deleted = repo.delete_meeting(meeting_id, owner_id=user.subject)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meeting not found")
    await _delete_meeting_source_asset(source_url, storage)


@router.get("/meetings/{meeting_id}/tasks")
def list_meeting_tasks(meeting_id: str, user: CurrentUser, repo: MeetingsRepositoryPort = Depends(_repo)):
    meeting = repo.get_meeting(meeting_id, owner_id=user.subject)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return repo.list_tasks(meeting_id=meeting_id, owner_id=user.subject)


@router.get("/tasks")
def list_tasks(
        user: CurrentUser,
        status: str | None = Query(default=None),
        repo: MeetingsRepositoryPort = Depends(_repo),
):
    if status and status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status filter")
    return repo.list_tasks(status=status, owner_id=user.subject)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, user: CurrentUser, repo: MeetingsRepositoryPort = Depends(_repo)):
    task = repo.get_task(task_id, owner_id=user.subject)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, payload: TaskUpdate, user: CurrentUser, repo: MeetingsRepositoryPort = Depends(_repo)):
    try:
        return repo.update_task(task_id, payload.model_dump(exclude_unset=True), owner_id=user.subject)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/bulk-approve")
def bulk_approve_tasks(
        payload: BulkApproveRequest,
        user: CurrentUser,
        repo: MeetingsRepositoryPort = Depends(_repo),
        jira: Any = Depends(jira_dependency),
):
    service = PushTasksToJiraService(repo=repo, jira_client=jira)
    try:
        result = service.push(payload.ids, owner_id=user.subject, project_key=payload.projectKey)
    except JiraClientError as exc:
        message = str(exc)
        status = 400 if "project" in message.lower() else 502
        raise HTTPException(status_code=status, detail=message) from exc
    return {"updated": result.pushed, "pushed": result.pushed, "skipped": result.skipped}


@router.post("/tasks/bulk-reject")
def bulk_reject_tasks(payload: BulkAction, user: CurrentUser, repo: MeetingsRepositoryPort = Depends(_repo)):
    updated = repo.bulk_update_status(payload.ids, "rejected", owner_id=user.subject)
    return {"updated": updated}


@router.get("/users")
def list_users(user: CurrentUser, repo: MeetingsRepositoryPort = Depends(_repo)):
    return repo.list_users(owner_id=user.subject)


@router.get("/jira/projects", response_model=list[JiraProjectResponse])
def list_jira_projects(user: CurrentUser, jira: Any = Depends(jira_dependency)):
    def _safe_list(client: Any):
        try:
            return client.list_projects()
        except JiraClientError as exc:
            raise exc
        except Exception as exc:  # pragma: no cover - defensive
            raise JiraClientError(str(exc)) from exc

    last_error: str | None = None
    for client in (jira, get_jira_client()):
        if client is None:
            continue
        try:
            projects = _safe_list(client)
            return [JiraProjectResponse(key=project.key, name=project.name) for project in projects]
        except JiraClientError as exc:
            last_error = str(exc)
            continue
    detail = last_error or "Unable to list Jira projects."
    raise HTTPException(status_code=502, detail=detail)


@router.get("/confluence/spaces")
def list_confluence_spaces(
        user: CurrentUser,
        jira: Any = Depends(jira_dependency),
        limit: int = Query(default=25, ge=1, le=200),
):
    if not hasattr(jira, "list_confluence_spaces"):
        raise HTTPException(status_code=503, detail="Confluence MCP integration is not configured.")
    try:
        return jira.list_confluence_spaces(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/users/voice", response_model=VoiceUploadResponse, status_code=201)
async def upload_voice_sample(
        user: CurrentUser,
        displayName: str = Form(..., min_length=1),
        file: UploadFile = File(...),
        userId: str | None = Form(default=None),
        repo: MeetingsRepositoryPort = Depends(_repo),
        worker_storage: Any = Depends(optional_worker_blob_storage_service),
):
    if worker_storage is None:
        raise HTTPException(status_code=503, detail="Worker storage is not configured.")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Audio file is empty.")
    slug = _slugify_name(displayName)
    ext = Path(file.filename or "").suffix.lower()
    if not ext or len(ext) > 5:
        ext = ".mp3"
    filename = f"intro_{slug}{ext}"
    blob_url = await worker_storage.upload_blob(
        blob_name=filename,
        content=payload,
        content_type=file.content_type or "audio/mpeg",
    )
    try:
        if userId:
            repo.update_user_voice_sample(userId, displayName, blob_url, owner_id=user.subject)
            final_user_id = userId
        else:
            final_user_id = repo.register_voice_profile(
                display_name=displayName, voice_sample_path=blob_url, owner_id=user.subject
            )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    user_row = repo.get_user(final_user_id, owner_id=user.subject)
    return VoiceUploadResponse(
        userId=final_user_id,
        displayName=user_row["displayName"] if user_row else displayName,
        voiceSamplePath=blob_url,
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
        _user: CurrentUser,
        storage: Any = Depends(optional_blob_storage_service),
):
    backend = (get_settings().ingest.backend or "azure").strip().lower()
    if backend != "azure":
        raise HTTPException(status_code=400, detail="SAS upload is available only when INGEST_BACKEND=azure.")
    if not isinstance(storage, BlobStorageService):
        raise HTTPException(status_code=503, detail="Azure blob storage is not configured.")
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


@router.post("/uploads/local", response_model=LocalUploadResponse)
async def create_local_upload(
        _user: CurrentUser,
        file: UploadFile = File(...),
        meetingId: str | None = Form(default=None),
        storage: Any = Depends(optional_blob_storage_service),
):
    backend = (get_settings().ingest.backend or "azure").strip().lower()
    if backend != "local":
        raise HTTPException(status_code=400, detail="Local upload is available only when INGEST_BACKEND=local.")
    if not hasattr(storage, "upload_blob"):
        raise HTTPException(status_code=503, detail="Local storage is not configured.")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Audio file is empty.")

    meeting_id = (meetingId or str(uuid.uuid4())).strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", meeting_id):
        raise HTTPException(status_code=400, detail="meetingId has an invalid format.")
    safe_name = Path(file.filename or "uploaded_file").name.replace(" ", "_").strip()
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Uploaded filename is invalid.")
    blob_path = f"{meeting_id}/{safe_name}"
    try:
        blob_url = await storage.upload_blob(
            blob_name=blob_path,
            content=payload,
            content_type=file.content_type or "application/octet-stream",
        )
    except (LocalStorageError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LocalUploadResponse(
        blobUrl=blob_url,
        blobPath=blob_path,
        meetingId=meeting_id,
    )


@router.post("/meetings/import", status_code=202)
async def import_meeting(
        payload: MeetingImportRequest,
        user: CurrentUser,
        command: SubmitMeetingImportCommand = Depends(submit_import_command),
):
    try:
        meeting_id = await command.execute(
            MeetingImportPayload(
                title=payload.title,
                started_at=payload.startedAt,
                blob_url=payload.blobUrl,
                original_filename=payload.originalFilename,
                meeting_id=payload.meetingId,
                project_key=payload.projectKey,
                owner_id=user.subject,
                atlassian_access_token=user.access_token,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"meetingId": meeting_id, "status": "queued"}


def _slugify_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().lower()
    slug = re.sub(r"[^\w]+", "_", normalized, flags=re.UNICODE)
    slug = slug.strip("_")
    return slug or "speaker"
