from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.dependencies import get_data_repository
from backend.db.storage import SqliteMeetingsRepository, TASK_STATUSES

router = APIRouter(prefix="/api", tags=["ui"])


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


def _repo(repo: SqliteMeetingsRepository = Depends(get_data_repository)) -> SqliteMeetingsRepository:
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
