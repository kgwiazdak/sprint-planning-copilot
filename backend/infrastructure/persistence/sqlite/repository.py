from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Iterable, Optional

from backend.audit import log_meeting_access
from backend.domain.ports import MeetingsRepositoryPort
from backend.domain.status import MeetingStatus
from backend.schemas import ExtractionResult
from . import mappers
from .constants import ISSUE_TYPES, PRIORITIES, TASK_STATUSES
from .database import SqliteDatabase, utc_now_iso


class SqliteMeetingsRepository(MeetingsRepositoryPort):
    """SQLite-backed repository providing CRUD helpers for meetings and tasks."""

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
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    m.id,
                    m.title,
                    m.started_at,
                    m.status,
                    m.created_at,
                    COALESCE(dc.count, 0) AS draft_count
                FROM meetings m
                LEFT JOIN (
                    SELECT meeting_id, COUNT(*) AS count
                    FROM tasks
                    WHERE status = 'draft'
                    GROUP BY meeting_id
                ) AS dc ON dc.meeting_id = m.id
                WHERE m.owner_id = ?
                ORDER BY m.started_at DESC
                """
                ,
                (owner_id,),
            ).fetchall()
            return [mappers.serialize_meeting_row(row) for row in rows]
        finally:
            conn.close()

    def get_meeting(self, meeting_id: str, *, owner_id: str) -> dict[str, Any] | None:
        self._audit("get", meeting_id=meeting_id)
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT
                    m.id,
                    m.title,
                    m.started_at,
                    m.status,
                    m.created_at,
                    COALESCE(dc.count, 0) AS draft_count
                FROM meetings m
                LEFT JOIN (
                    SELECT meeting_id, COUNT(*) AS count
                    FROM tasks
                    WHERE status = 'draft'
                    GROUP BY meeting_id
                ) AS dc ON dc.meeting_id = m.id
                WHERE m.id = ? AND m.owner_id = ?
                """,
                (meeting_id, owner_id),
            ).fetchone()
            if not row:
                return None
            return mappers.serialize_meeting_row(row)
        finally:
            conn.close()

    def create_meeting(
            self,
            *,
            title: str,
            started_at: str,
            source_url: str | None,
            source_text: str | None,
            owner_id: str,
    ) -> dict[str, Any]:
        meeting_id = str(uuid.uuid4())
        self._audit("create", meeting_id=meeting_id)
        now = utc_now_iso()
        conn = self._db.connect()
        try:
            conn.execute(
                """
                INSERT INTO meetings(id, title, transcript, created_at, started_at, status, source_url, source_text, owner_id)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    meeting_id,
                    title,
                    source_text,
                    now,
                    started_at,
                    "pending",
                    source_url,
                    source_text,
                    owner_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_meeting(meeting_id, owner_id=owner_id)

    def update_meeting(
            self, meeting_id: str, *, title: str | None, started_at: str | None, owner_id: str
    ) -> dict[str, Any]:
        self._audit("update", meeting_id=meeting_id)
        fields = []
        params: list[Any] = []
        if title is not None:
            fields.append("title = ?")
            params.append(title)
        if started_at is not None:
            fields.append("started_at = ?")
            params.append(started_at)
        if not fields:
            meeting = self.get_meeting(meeting_id, owner_id=owner_id)
            if meeting is None:
                raise ValueError("Meeting not found")
            return meeting

        params.append(meeting_id)
        params.append(owner_id)
        conn = self._db.connect()
        try:
            cur = conn.execute(
                f"UPDATE meetings SET {', '.join(fields)} WHERE id = ? AND owner_id = ?",
                params,
            )
            if cur.rowcount == 0:
                raise ValueError("Meeting not found")
            conn.commit()
        finally:
            conn.close()
        meeting = self.get_meeting(meeting_id, owner_id=owner_id)
        if meeting is None:
            raise ValueError("Meeting not found")
        return meeting

    def delete_meeting(self, meeting_id: str, *, owner_id: str) -> bool:
        self._audit("delete", meeting_id=meeting_id)
        conn = self._db.connect()
        try:
            cur = conn.execute("DELETE FROM meetings WHERE id = ? AND owner_id = ?", (meeting_id, owner_id))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # --- Task queries ----------------------------------------------------
    def list_tasks(
            self, *, meeting_id: str | None = None, status: str | None = None, owner_id: str
    ) -> list[dict[str, Any]]:
        self._audit("list_tasks", meeting_id=meeting_id, resource="task", details={"status": status})
        conn = self._db.connect()
        try:
            query = """
                SELECT t.*, u.display_name AS assignee_display_name, u.jira_account_id
                FROM tasks t
                JOIN meetings m ON m.id = t.meeting_id
                LEFT JOIN users u ON u.id = t.assignee_id
                    AND (u.owner_id = ? OR u.owner_id IS NULL OR u.owner_id = 'system')
                WHERE m.owner_id = ?
            """
            params: list[Any] = [owner_id, owner_id]
            if meeting_id:
                query += " AND t.meeting_id = ?"
                params.append(meeting_id)
            if status:
                query += " AND t.status = ?"
                params.append(status)
            query += " ORDER BY t.created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [mappers.serialize_task_row(row) for row in rows]
        finally:
            conn.close()

    def get_task(self, task_id: str, *, owner_id: str) -> dict[str, Any] | None:
        self._audit("get_task", resource="task", details={"task_id": task_id})
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT t.*, u.display_name AS assignee_display_name, u.jira_account_id
                FROM tasks t
                JOIN meetings m ON m.id = t.meeting_id
                LEFT JOIN users u ON u.id = t.assignee_id
                    AND (u.owner_id = ? OR u.owner_id IS NULL OR u.owner_id = 'system')
                WHERE t.id = ? AND m.owner_id = ?
                """,
                (owner_id, task_id, owner_id),
            ).fetchone()
            return mappers.serialize_task_row(row) if row else None
        finally:
            conn.close()

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
        fields = []
        params: list[Any] = []
        for key, column in allowed.items():
            if key not in payload or payload[key] is None:
                continue
            value = payload[key]
            if key == "labels":
                value = json.dumps(value)
            fields.append(f"{column} = ?")
            params.append(value)
        if not fields:
            task = self.get_task(task_id, owner_id=owner_id)
            if task is None:
                raise ValueError("Task not found")
            return task
        fields.append("owner_id = COALESCE(owner_id, ?)")
        params.append(owner_id)
        fields.append("updated_at = ?")
        params.append(utc_now_iso())
        params.append(task_id)
        conn = self._db.connect()
        try:
            cur = conn.execute(
                f"""
                UPDATE tasks
                SET {', '.join(fields)}
                WHERE id = ?
                  AND meeting_id IN (SELECT id FROM meetings WHERE owner_id = ?)
                """,
                params,
            )
            if cur.rowcount == 0:
                raise ValueError("Task not found")
            conn.commit()
            row = conn.execute(
                "SELECT meeting_id FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        finally:
            conn.close()
        meeting_id = row["meeting_id"] if row else None
        task = self.get_task(task_id, owner_id=owner_id)
        if task is None:
            raise ValueError("Task not found")
        return task

    def bulk_update_status(self, ids: Iterable[str], status: str, *, owner_id: str) -> int:
        ids = list(ids)
        self._audit("bulk_update_status", resource="task", details={"ids": ids, "status": status})
        if not ids:
            return 0
        conn = self._db.connect()
        try:
            placeholders = ",".join("?" for _ in ids)
            params = [status, utc_now_iso(), owner_id, *ids, owner_id]
            cur = conn.execute(
                f"""
                UPDATE tasks
                SET status = ?, updated_at = ?, owner_id = COALESCE(owner_id, ?)
                WHERE id IN ({placeholders})
                  AND meeting_id IN (SELECT id FROM meetings WHERE owner_id = ?)
                """,
                params,
            )
            conn.commit()
            updated_count = cur.rowcount
        finally:
            conn.close()
        return updated_count

    def get_tasks_by_ids(self, ids: Iterable[str], *, owner_id: str) -> list[dict[str, Any]]:
        task_ids = [task_id for task_id in ids if task_id]
        self._audit("get_tasks_by_ids", resource="task", details={"ids": task_ids})
        if not task_ids:
            return []
        placeholders = ",".join("?" for _ in task_ids)
        conn = self._db.connect()
        try:
            rows = conn.execute(
                f"""
                SELECT
                    t.*,
                    u.jira_account_id AS assignee_jira_account_id,
                    u.display_name AS assignee_display_name
                FROM tasks t
                JOIN meetings m ON m.id = t.meeting_id
                LEFT JOIN users u ON u.id = t.assignee_id
                    AND (u.owner_id = ? OR u.owner_id IS NULL OR u.owner_id = 'system')
                WHERE t.id IN ({placeholders}) AND m.owner_id = ?
                """,
                [owner_id, *task_ids, owner_id],
            ).fetchall()
            return [mappers.serialize_task_row(row) for row in rows]
        finally:
            conn.close()

    def mark_task_pushed_to_jira(
            self, task_id: str, *, issue_key: str, issue_url: str | None, owner_id: str
    ) -> None:
        self._audit(
            "mark_task_pushed_to_jira",
            resource="task",
            details={"task_id": task_id, "issue_key": issue_key, "issue_url": issue_url},
        )
        now = utc_now_iso()
        conn = self._db.connect()
        try:
            cur = conn.execute(
                """
                UPDATE tasks
                SET status = 'approved',
                    jira_issue_key = ?,
                    jira_issue_url = ?,
                    pushed_to_jira_at = ?,
                    updated_at = ?,
                    owner_id = COALESCE(owner_id, ?)
                WHERE id = ?
                  AND meeting_id IN (SELECT id FROM meetings WHERE owner_id = ?)
                """,
                (issue_key, issue_url, now, now, owner_id, task_id, owner_id),
            )
            if cur.rowcount == 0:
                raise ValueError("Task not found")
            conn.commit()
        finally:
            conn.close()

    def list_users(self, *, owner_id: str) -> list[dict[str, Any]]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, display_name, email, jira_account_id, voice_sample_path
                FROM users
                WHERE owner_id = ?
                ORDER BY display_name
                """,
                (owner_id,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "displayName": row["display_name"],
                    "email": row["email"],
                    "jiraAccountId": row["jira_account_id"],
                    "voiceSamplePath": row["voice_sample_path"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def get_user(self, user_id: str, *, owner_id: str) -> dict[str, Any] | None:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT id, display_name, email, jira_account_id FROM users WHERE id = ? AND owner_id = ?",
                (user_id, owner_id),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "displayName": row["display_name"],
                "email": row["email"],
                "jiraAccountId": row["jira_account_id"],
            }
        finally:
            conn.close()

    def update_user_jira_account(self, user_id: str, account_id: str, *, owner_id: str) -> None:
        conn = self._db.connect()
        try:
            cur = conn.execute(
                "UPDATE users SET jira_account_id = ? WHERE id = ? AND owner_id = ?",
                (account_id, user_id, owner_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                raise ValueError("User not found")
        finally:
            conn.close()

    # --- Ports implementation -------------------------------------------
    def create_meeting_stub(
            self,
            *,
            meeting_id: str,
            title: str,
            started_at: str,
            blob_url: str,
            owner_id: str,
    ) -> None:
        self._audit("create_stub", meeting_id=meeting_id, details={"title": title})
        now = utc_now_iso()
        conn = self._db.connect()
        try:
            existing_owner = conn.execute(
                "SELECT owner_id FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
            if existing_owner and existing_owner["owner_id"] not in (None, owner_id):
                raise ValueError("Meeting already exists for a different user")
            conn.execute(
                """
                INSERT INTO meetings(id, title, created_at, started_at, status, source_url, owner_id)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    started_at=excluded.started_at,
                    status='queued',
                    source_url=excluded.source_url,
                    owner_id=excluded.owner_id
                """,
                (
                    meeting_id,
                    title,
                    now,
                    started_at,
                    MeetingStatus.QUEUED.value,
                    blob_url,
                    owner_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def update_meeting_status(self, meeting_id: str, status: str, *, owner_id: str | None = None) -> None:
        self._audit("status_change", meeting_id=meeting_id, details={"status": status})
        conn = self._db.connect()
        try:
            if owner_id:
                conn.execute(
                    """
                    UPDATE meetings
                    SET status = ?, owner_id = COALESCE(owner_id, ?)
                    WHERE id = ? AND (owner_id = ? OR owner_id IS NULL)
                    """,
                    (status, owner_id, meeting_id, owner_id),
                )
            else:
                conn.execute("UPDATE meetings SET status = ? WHERE id = ?", (status, meeting_id))
            conn.commit()
        finally:
            conn.close()

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
        conn = self._db.connect()
        try:
            existing = conn.execute(
                "SELECT owner_id FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
            current_owner = existing["owner_id"] if existing else None
            final_owner = owner_id or current_owner
            if existing and current_owner and owner_id and current_owner != owner_id:
                raise ValueError("Meeting belongs to a different user")
            if existing:
                conn.execute(
                    """
                    UPDATE meetings
                    SET title = ?, transcript = ?, started_at = ?, status = 'completed',
                        source_text = ?, source_url = COALESCE(source_url, ?), owner_id = COALESCE(owner_id, ?)
                    WHERE id = ? AND (owner_id = ? OR owner_id IS NULL)
                    """,
                    (
                        meeting_title,
                        transcript,
                        meeting_started_at,
                        transcript,
                        blob_url,
                        final_owner,
                        meeting_id,
                        final_owner,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO meetings(id, title, transcript, created_at, started_at, status, source_text, source_url, owner_id)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        meeting_id,
                        meeting_title,
                        transcript,
                        now,
                        meeting_started_at,
                        MeetingStatus.COMPLETED.value,
                        transcript,
                        blob_url,
                        final_owner,
                    ),
                )
            conn.execute("DELETE FROM tasks WHERE meeting_id = ?", (meeting_id,))
            conn.execute("DELETE FROM extraction_runs WHERE meeting_id = ?", (meeting_id,))
            run_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO extraction_runs(id, meeting_id, payload_json, created_at)
                VALUES(?,?,?,?)
                """,
                (run_id, meeting_id, json.dumps(result_model.dict()), now),
            )
            for task in result_model.tasks:
                labels = getattr(task, "labels", []) or []
                source_quote = (task.quotes or [None])[0] if hasattr(task, "quotes") else None
                assignee_name = getattr(task, "assignee_name", None)
                assignee_id = None
                if assignee_name:
                    assignee_id = self._find_user_id_by_name(conn, assignee_name, owner_id)
                conn.execute(
                    """
                    INSERT INTO tasks(
                        id, meeting_id, summary, description, issue_type, priority, owner_id,
                        story_points, assignee_id, labels, status, source_quote,
                        created_at, updated_at
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(uuid.uuid4()),
                        meeting_id,
                        task.summary,
                        task.description,
                        task.issue_type.value,
                        task.priority.value,
                        final_owner,
                        getattr(task, "story_points", None),
                        assignee_id,
                        json.dumps(labels),
                        "draft",
                        source_quote,
                        now,
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return meeting_id, run_id

    def register_voice_profile(
            self, *, display_name: str, voice_sample_path: str | None = None, owner_id: str
    ) -> str:
        normalized = display_name.strip()
        if not normalized:
            raise ValueError("display_name is required")
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT id FROM users WHERE lower(display_name) = lower(?) AND owner_id = ?",
                (normalized, owner_id),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE users
                    SET display_name = ?, voice_sample_path = COALESCE(?, voice_sample_path)
                    WHERE id = ? AND owner_id = ?
                    """,
                    (normalized, voice_sample_path, row["id"], owner_id),
                )
                conn.commit()
                return row["id"]
            user_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO users(id, display_name, voice_sample_path, owner_id) VALUES(?,?,?,?)",
                (user_id, normalized, voice_sample_path, owner_id),
            )
            conn.commit()
            return user_id
        finally:
            conn.close()

    def update_user_voice_sample(
            self, user_id: str, display_name: str, voice_sample_path: str, *, owner_id: str
    ) -> str:
        normalized = display_name.strip()
        if not normalized:
            raise ValueError("display_name is required")
        conn = self._db.connect()
        try:
            row = conn.execute("SELECT id FROM users WHERE id = ? AND owner_id = ?", (user_id, owner_id)).fetchone()
            if not row:
                raise ValueError("User not found")
            conn.execute(
                "UPDATE users SET display_name = ?, voice_sample_path = ? WHERE id = ? AND owner_id = ?",
                (normalized, voice_sample_path, user_id, owner_id),
            )
            conn.commit()
            return user_id
        finally:
            conn.close()

    def _find_user_id_by_name(self, conn: sqlite3.Connection, display_name: str, owner_id: str) -> str | None:
        row = conn.execute(
            """
            SELECT id
            FROM users
            WHERE lower(display_name) = lower(?)
              AND (owner_id = ? OR owner_id IS NULL OR owner_id = 'system')
            """,
            (display_name.strip(), owner_id),
        ).fetchone()
        return row["id"] if row else None


__all__ = [
    "SqliteMeetingsRepository",
    "TASK_STATUSES",
    "ISSUE_TYPES",
    "PRIORITIES",
]
