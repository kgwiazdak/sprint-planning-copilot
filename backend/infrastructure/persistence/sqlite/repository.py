from __future__ import annotations

import json
import uuid
from typing import Any, Iterable, Optional

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from backend.audit import log_meeting_access
from backend.domain.ports import MeetingsRepositoryPort
from backend.domain.status import MeetingStatus
from backend.schemas import ExtractionResult
from . import mappers
from .constants import ISSUE_TYPES, PRIORITIES, TASK_STATUSES
from .database import (
    ExtractionRun,
    Meeting,
    SqliteDatabase,
    Task,
    User,
    utc_now_iso,
)


class SqliteMeetingsRepository(MeetingsRepositoryPort):
    """SQLite-backed repository implemented with SQLAlchemy."""

    def __init__(self, db_url: str | None = None) -> None:
        self._db = SqliteDatabase(db_url)
        log_meeting_access("repository_init", details={"backend": "sqlite"})

    def _audit(
            self,
            action: str,
            *,
            meeting_id: str | None = None,
            resource: str = "meeting",
            details: dict[str, Any] | None = None,
    ) -> None:
        log_meeting_access(action, meeting_id=meeting_id, resource=resource, details=details)

    # --- Meeting queries -------------------------------------------------
    def list_meetings(self, *, owner_id: str) -> list[dict[str, Any]]:
        self._audit("list")
        with self._db.session() as session:
            draft_counts = (
                session.query(Task.meeting_id, func.count(Task.id).label("draft_count"))
                .filter(Task.status == "draft")
                .group_by(Task.meeting_id)
                .subquery()
            )
            results = (
                session.query(Meeting, func.coalesce(draft_counts.c.draft_count, 0))
                .outerjoin(draft_counts, Meeting.id == draft_counts.c.meeting_id)
                .filter(Meeting.owner_id == owner_id)
                .order_by(Meeting.started_at.desc())
                .all()
            )
            return [mappers.serialize_meeting_row(meeting, draft_count) for meeting, draft_count in results]

    def get_meeting(self, meeting_id: str, *, owner_id: str) -> dict[str, Any] | None:
        self._audit("get", meeting_id=meeting_id)
        with self._db.session() as session:
            draft_counts = (
                session.query(Task.meeting_id, func.count(Task.id).label("draft_count"))
                .filter(Task.status == "draft")
                .group_by(Task.meeting_id)
                .subquery()
            )
            result = (
                session.query(Meeting, func.coalesce(draft_counts.c.draft_count, 0))
                .outerjoin(draft_counts, Meeting.id == draft_counts.c.meeting_id)
                .filter(Meeting.id == meeting_id, Meeting.owner_id == owner_id)
                .first()
            )
            if not result:
                return None
            meeting, draft_count = result
            return mappers.serialize_meeting_row(meeting, draft_count)

    def create_meeting(
            self,
            *,
            title: str,
            started_at: str,
            source_url: str | None,
            source_text: str | None,
            project_key: str | None,
            owner_id: str,
    ) -> dict[str, Any]:
        meeting_id = str(uuid.uuid4())
        self._audit("create", meeting_id=meeting_id)
        now = utc_now_iso()
        meeting = Meeting(
            id=meeting_id,
            title=title,
            transcript=source_text,
            created_at=now,
            started_at=started_at,
            status="pending",
            source_url=source_url,
            source_text=source_text,
            project_key=project_key,
            owner_id=owner_id,
        )
        with self._db.session() as session:
            session.add(meeting)
            session.commit()
        created = self.get_meeting(meeting_id, owner_id=owner_id)
        if created is None:
            raise ValueError("Failed to create meeting")
        return created

    def update_meeting(
            self, meeting_id: str, *, title: str | None, started_at: str | None, owner_id: str
    ) -> dict[str, Any]:
        self._audit("update", meeting_id=meeting_id)
        with self._db.session() as session:
            meeting = (
                session.query(Meeting)
                .filter(Meeting.id == meeting_id, Meeting.owner_id == owner_id)
                .first()
            )
            if not meeting:
                raise ValueError("Meeting not found")
            if title is not None:
                meeting.title = title
            if started_at is not None:
                meeting.started_at = started_at
            session.commit()
        updated = self.get_meeting(meeting_id, owner_id=owner_id)
        if updated is None:
            raise ValueError("Meeting not found")
        return updated

    def delete_meeting(self, meeting_id: str, *, owner_id: str) -> bool:
        self._audit("delete", meeting_id=meeting_id)
        with self._db.session() as session:
            meeting = (
                session.query(Meeting)
                .filter(Meeting.id == meeting_id, Meeting.owner_id == owner_id)
                .first()
            )
            if not meeting:
                return False
            session.delete(meeting)
            session.commit()
            return True

    # --- Task queries ----------------------------------------------------
    def list_tasks(
            self, *, meeting_id: str | None = None, status: str | None = None, owner_id: str
    ) -> list[dict[str, Any]]:
        self._audit("list_tasks", meeting_id=meeting_id, resource="task", details={"status": status})
        with self._db.session() as session:
            query = (
                session.query(Task, User)
                .join(Meeting, Task.meeting_id == Meeting.id)
                .outerjoin(
                    User,
                    (User.id == Task.assignee_id)
                    & or_(User.owner_id == owner_id, User.owner_id.is_(None), User.owner_id == "system"),
                )
                .filter(Meeting.owner_id == owner_id)
            )
            if meeting_id:
                query = query.filter(Task.meeting_id == meeting_id)
            if status:
                query = query.filter(Task.status == status)
            rows = query.order_by(Task.created_at.desc()).all()
            return [mappers.serialize_task_row(task, assignee) for task, assignee in rows]

    def get_task(self, task_id: str, *, owner_id: str) -> dict[str, Any] | None:
        self._audit("get_task", resource="task", details={"task_id": task_id})
        with self._db.session() as session:
            row = (
                session.query(Task, User)
                .join(Meeting, Task.meeting_id == Meeting.id)
                .outerjoin(
                    User,
                    (User.id == Task.assignee_id)
                    & or_(User.owner_id == owner_id, User.owner_id.is_(None), User.owner_id == "system"),
                )
                .filter(Task.id == task_id, Meeting.owner_id == owner_id)
                .first()
            )
            if not row:
                return None
            task, assignee = row
            return mappers.serialize_task_row(task, assignee)

    def update_task(self, task_id: str, payload: dict[str, Any], *, owner_id: str) -> dict[str, Any]:
        self._audit("update_task", resource="task", details={"task_id": task_id})
        allowed = {
            "summary": "summary",
            "description": "description",
            "issueType": "issue_type",
            "priority": "priority",
            "storyPoints": "story_points",
            "assigneeId": "assignee_id",
            "labels": "labels",
            "status": "status",
        }
        with self._db.session() as session:
            task = (
                session.query(Task)
                .join(Meeting, Task.meeting_id == Meeting.id)
                .filter(Task.id == task_id, Meeting.owner_id == owner_id)
                .first()
            )
            if not task:
                raise ValueError("Task not found")
            updated = False
            for key, attr in allowed.items():
                if key not in payload or payload[key] is None:
                    continue
                value = payload[key]
                if key == "labels":
                    value = json.dumps(value)
                setattr(task, attr, value)
                updated = True
            if not updated:
                session.expunge(task)
                session.close()
                existing = self.get_task(task_id, owner_id=owner_id)
                if existing is None:
                    raise ValueError("Task not found")
                return existing
            task.owner_id = task.owner_id or owner_id
            task.updated_at = utc_now_iso()
            session.commit()
        updated_task = self.get_task(task_id, owner_id=owner_id)
        if updated_task is None:
            raise ValueError("Task not found")
        return updated_task

    def bulk_update_status(self, ids: Iterable[str], status: str, *, owner_id: str) -> int:
        task_ids = [task_id for task_id in ids if task_id]
        self._audit("bulk_update_status", resource="task", details={"ids": task_ids, "status": status})
        if not task_ids:
            return 0
        now = utc_now_iso()
        with self._db.session() as session:
            stmt = (
                update(Task)
                .where(Task.id.in_(task_ids))
                .where(Task.meeting_id.in_(select(Meeting.id).where(Meeting.owner_id == owner_id)))
                .values(
                    status=status,
                    updated_at=now,
                    owner_id=func.coalesce(Task.owner_id, owner_id),
                )
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount or 0

    def get_tasks_by_ids(self, ids: Iterable[str], *, owner_id: str) -> list[dict[str, Any]]:
        task_ids = [task_id for task_id in ids if task_id]
        self._audit("get_tasks_by_ids", resource="task", details={"ids": task_ids})
        if not task_ids:
            return []
        with self._db.session() as session:
            rows = (
                session.query(Task, User)
                .join(Meeting, Task.meeting_id == Meeting.id)
                .outerjoin(
                    User,
                    (User.id == Task.assignee_id)
                    & or_(User.owner_id == owner_id, User.owner_id.is_(None), User.owner_id == "system"),
                )
                .filter(Task.id.in_(task_ids), Meeting.owner_id == owner_id)
                .all()
            )
            return [mappers.serialize_task_row(task, assignee) for task, assignee in rows]

    def mark_task_pushed_to_jira(
            self, task_id: str, *, issue_key: str, issue_url: str | None, owner_id: str
    ) -> None:
        self._audit(
            "mark_task_pushed_to_jira",
            resource="task",
            details={"task_id": task_id, "issue_key": issue_key, "issue_url": issue_url},
        )
        now = utc_now_iso()
        with self._db.session() as session:
            task = (
                session.query(Task)
                .join(Meeting, Task.meeting_id == Meeting.id)
                .filter(Task.id == task_id, Meeting.owner_id == owner_id)
                .first()
            )
            if not task:
                raise ValueError("Task not found")
            task.status = "approved"
            task.jira_issue_key = issue_key
            task.jira_issue_url = issue_url
            task.pushed_to_jira_at = now
            task.updated_at = now
            task.owner_id = task.owner_id or owner_id
            session.commit()

    def list_users(self, *, owner_id: str) -> list[dict[str, Any]]:
        with self._db.session() as session:
            users = (
                session.query(User)
                .filter(User.owner_id == owner_id)
                .order_by(User.display_name.asc())
                .all()
            )
            return [
                {
                    "id": user.id,
                    "displayName": user.display_name,
                    "email": user.email,
                    "jiraAccountId": user.jira_account_id,
                    "voiceSamplePath": user.voice_sample_path,
                }
                for user in users
            ]

    def get_user(self, user_id: str, *, owner_id: str) -> dict[str, Any] | None:
        with self._db.session() as session:
            user = (
                session.query(User)
                .filter(User.id == user_id, User.owner_id == owner_id)
                .first()
            )
            if not user:
                return None
            return {
                "id": user.id,
                "displayName": user.display_name,
                "email": user.email,
                "jiraAccountId": user.jira_account_id,
            }

    def update_user_jira_account(self, user_id: str, account_id: str, *, owner_id: str) -> None:
        with self._db.session() as session:
            user = (
                session.query(User)
                .filter(User.id == user_id, User.owner_id == owner_id)
                .first()
            )
            if not user:
                raise ValueError("User not found")
            user.jira_account_id = account_id
            session.commit()

    # --- Ports implementation -------------------------------------------
    def create_meeting_stub(
            self,
            *,
            meeting_id: str,
            title: str,
            started_at: str,
            blob_url: str,
            project_key: str | None,
            owner_id: str,
    ) -> None:
        self._audit("create_stub", meeting_id=meeting_id, details={"title": title})
        now = utc_now_iso()
        with self._db.session() as session:
            meeting = session.get(Meeting, meeting_id)
            if meeting and meeting.owner_id not in (None, owner_id):
                raise ValueError("Meeting already exists for a different user")
            if meeting:
                meeting.title = title
                meeting.started_at = started_at
                meeting.status = MeetingStatus.QUEUED.value
                meeting.source_url = blob_url
                if project_key:
                    meeting.project_key = project_key
                meeting.owner_id = owner_id
            else:
                session.add(
                    Meeting(
                        id=meeting_id,
                        title=title,
                        created_at=now,
                        started_at=started_at,
                        status=MeetingStatus.QUEUED.value,
                        source_url=blob_url,
                        project_key=project_key,
                        owner_id=owner_id,
                    )
                )
            session.commit()

    def update_meeting_status(self, meeting_id: str, status: str, *, owner_id: str | None = None) -> None:
        self._audit("status_change", meeting_id=meeting_id, details={"status": status})
        with self._db.session() as session:
            meeting = session.get(Meeting, meeting_id)
            if not meeting:
                return
            if owner_id and meeting.owner_id not in (None, owner_id):
                return
            meeting.status = status
            if owner_id and not meeting.owner_id:
                meeting.owner_id = owner_id
            session.commit()

    def store_meeting_and_result(
            self,
            filename: str,
            transcript: str,
            result_model: ExtractionResult,
            *,
            meeting_id: Optional[str] = None,
            title: Optional[str] = None,
            started_at: Optional[str] = None,
            blob_url: Optional[str] = None,
            project_key: Optional[str] = None,
            owner_id: str | None,
    ) -> tuple[str, str]:
        meeting_id = meeting_id or str(uuid.uuid4())
        self._audit(
            "store_result",
            meeting_id=meeting_id,
            details={"filename": filename, "tasks": len(result_model.tasks)},
        )
        now = utc_now_iso()
        meeting_title = title or filename
        meeting_started_at = started_at or now
        with self._db.session() as session:
            meeting = session.get(Meeting, meeting_id)
            current_owner = meeting.owner_id if meeting else None
            final_owner = owner_id or current_owner
            if meeting and current_owner and owner_id and current_owner != owner_id:
                raise ValueError("Meeting belongs to a different user")
            if meeting:
                meeting.title = meeting_title
                meeting.transcript = transcript
                meeting.started_at = meeting_started_at
                meeting.status = MeetingStatus.COMPLETED.value
                meeting.source_text = transcript
                meeting.source_url = meeting.source_url or blob_url
                meeting.project_key = meeting.project_key or project_key
                meeting.owner_id = meeting.owner_id or final_owner
            else:
                session.add(
                    Meeting(
                        id=meeting_id,
                        title=meeting_title,
                        transcript=transcript,
                        created_at=now,
                        started_at=meeting_started_at,
                        status=MeetingStatus.COMPLETED.value,
                        source_text=transcript,
                        source_url=blob_url,
                        project_key=project_key,
                        owner_id=final_owner,
                    )
                )
            session.execute(delete(Task).where(Task.meeting_id == meeting_id))
            session.execute(delete(ExtractionRun).where(ExtractionRun.meeting_id == meeting_id))
            run_id = str(uuid.uuid4())
            session.add(
                ExtractionRun(
                    id=run_id,
                    meeting_id=meeting_id,
                    payload_json=json.dumps(result_model.model_dump()),
                    created_at=now,
                )
            )
            for task in result_model.tasks:
                labels = getattr(task, "labels", []) or []
                source_quote = (task.quotes or [None])[0] if getattr(task, "quotes", None) else None
                assignee_name = getattr(task, "assignee_name", None)
                assignee_id = None
                if assignee_name:
                    assignee_id = self._find_user_id_by_name(session, assignee_name, final_owner or owner_id)
                session.add(
                    Task(
                        id=str(uuid.uuid4()),
                        meeting_id=meeting_id,
                        summary=task.summary,
                        description=task.description,
                        issue_type=task.issue_type.value,
                        priority=task.priority.value,
                        story_points=getattr(task, "story_points", None),
                        assignee_id=assignee_id,
                        labels=json.dumps(labels),
                        status="draft",
                        source_quote=source_quote,
                        created_at=now,
                        updated_at=now,
                        owner_id=final_owner,
                    )
                )
            session.commit()
        return meeting_id, run_id

    def register_voice_profile(
            self, *, display_name: str, voice_sample_path: str | None = None, owner_id: str
    ) -> str:
        normalized = display_name.strip()
        if not normalized:
            raise ValueError("display_name is required")
        with self._db.session() as session:
            existing = (
                session.query(User)
                .filter(func.lower(User.display_name) == normalized.lower(), User.owner_id == owner_id)
                .first()
            )
            if existing:
                if voice_sample_path:
                    existing.voice_sample_path = voice_sample_path
                existing.display_name = normalized
                session.commit()
                return existing.id
            user_id = str(uuid.uuid4())
            session.add(
                User(
                    id=user_id,
                    display_name=normalized,
                    voice_sample_path=voice_sample_path,
                    owner_id=owner_id,
                )
            )
            session.commit()
            return user_id

    def update_user_voice_sample(
            self, user_id: str, display_name: str, voice_sample_path: str, *, owner_id: str
    ) -> str:
        normalized = display_name.strip()
        if not normalized:
            raise ValueError("display_name is required")
        with self._db.session() as session:
            user = (
                session.query(User)
                .filter(User.id == user_id, User.owner_id == owner_id)
                .first()
            )
            if not user:
                raise ValueError("User not found")
            user.display_name = normalized
            user.voice_sample_path = voice_sample_path
            session.commit()
            return user_id

    def _find_user_id_by_name(self, session: Session, display_name: str, owner_id: str | None) -> str | None:
        normalized = display_name.strip()
        if not normalized:
            return None
        user = (
            session.query(User)
            .filter(
                func.lower(User.display_name) == normalized.lower(),
                or_(
                    User.owner_id == owner_id,
                    User.owner_id.is_(None),
                    User.owner_id == "system",
                ),
            )
            .first()
        )
        return user.id if user else None


__all__ = [
    "SqliteMeetingsRepository",
    "TASK_STATUSES",
    "ISSUE_TYPES",
    "PRIORITIES",
]
