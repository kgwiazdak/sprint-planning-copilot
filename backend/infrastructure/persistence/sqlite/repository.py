from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Iterable, Optional

from backend.domain.ports import MeetingsRepositoryPort
from backend.schemas import ExtractionResult

from .constants import ISSUE_TYPES, PRIORITIES, TASK_STATUSES
from .database import SqliteDatabase, utc_now_iso
from . import mappers


class SqliteMeetingsRepository(MeetingsRepositoryPort):
    """SQLite-backed repository providing CRUD helpers for meetings and tasks."""

    def __init__(self, db_url: str | None = None) -> None:
        self._db = SqliteDatabase(db_url)

    # --- Meeting queries -------------------------------------------------
    def list_meetings(self) -> list[dict[str, Any]]:
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
                ORDER BY m.started_at DESC
                """
            ).fetchall()
            return [mappers.serialize_meeting_row(row) for row in rows]
        finally:
            conn.close()

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
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
                WHERE m.id = ?
                """,
                (meeting_id,),
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
    ) -> dict[str, Any]:
        meeting_id = str(uuid.uuid4())
        now = utc_now_iso()
        conn = self._db.connect()
        try:
            conn.execute(
                """
                INSERT INTO meetings(id, title, transcript, created_at, started_at, status, source_url, source_text)
                VALUES(?,?,?,?,?,?,?,?)
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
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_meeting(meeting_id)

    def update_meeting(self, meeting_id: str, *, title: str | None, started_at: str | None) -> dict[str, Any]:
        fields = []
        params: list[Any] = []
        if title is not None:
            fields.append("title = ?")
            params.append(title)
        if started_at is not None:
            fields.append("started_at = ?")
            params.append(started_at)
        if not fields:
            meeting = self.get_meeting(meeting_id)
            if meeting is None:
                raise ValueError("Meeting not found")
            return meeting

        params.append(meeting_id)
        conn = self._db.connect()
        try:
            cur = conn.execute(
                f"UPDATE meetings SET {', '.join(fields)} WHERE id = ?",
                params,
            )
            if cur.rowcount == 0:
                raise ValueError("Meeting not found")
            conn.commit()
        finally:
            conn.close()
        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            raise ValueError("Meeting not found")
        return meeting

    def delete_meeting(self, meeting_id: str) -> bool:
        conn = self._db.connect()
        try:
            cur = conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # --- Task queries ----------------------------------------------------
    def list_tasks(self, *, meeting_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        conn = self._db.connect()
        try:
            query = "SELECT * FROM tasks"
            clauses = []
            params: list[Any] = []
            if meeting_id:
                clauses.append("meeting_id = ?")
                params.append(meeting_id)
            if status:
                clauses.append("status = ?")
                params.append(status)
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [mappers.serialize_task_row(row) for row in rows]
        finally:
            conn.close()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        conn = self._db.connect()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return mappers.serialize_task_row(row) if row else None
        finally:
            conn.close()

    def update_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
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
            task = self.get_task(task_id)
            if task is None:
                raise ValueError("Task not found")
            return task

        fields.append("updated_at = ?")
        params.append(utc_now_iso())
        params.append(task_id)
        conn = self._db.connect()
        try:
            cur = conn.execute(
                f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?",
                params,
            )
            if cur.rowcount == 0:
                raise ValueError("Task not found")
            conn.commit()
            row = conn.execute("SELECT meeting_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        finally:
            conn.close()
        meeting_id = row["meeting_id"] if row else None
        if meeting_id:
            self._update_meeting_status(meeting_id)
        task = self.get_task(task_id)
        if task is None:
            raise ValueError("Task not found")
        return task

    def bulk_update_status(self, ids: Iterable[str], status: str) -> int:
        ids = list(ids)
        if not ids:
            return 0
        conn = self._db.connect()
        try:
            placeholders = ",".join("?" for _ in ids)
            params = [status, utc_now_iso(), *ids]
            cur = conn.execute(
                f"UPDATE tasks SET status = ?, updated_at = ? WHERE id IN ({placeholders})",
                params,
            )
            conn.commit()
            meeting_rows = conn.execute(
                f"SELECT DISTINCT meeting_id FROM tasks WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
            updated_count = cur.rowcount
        finally:
            conn.close()
        for row in meeting_rows:
            self._update_meeting_status(row["meeting_id"])
        return updated_count

    def list_users(self) -> list[dict[str, Any]]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT id, display_name, email FROM users ORDER BY display_name"
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "displayName": row["display_name"],
                    "email": row["email"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    # --- Ports implementation -------------------------------------------
    def store_meeting_and_result(
        self,
        filename: str,
        transcript: str,
        result_model: ExtractionResult,
        *,
        meeting_id: Optional[str] = None,
    ) -> tuple[str, str]:
        meeting_id = meeting_id or str(uuid.uuid4())
        now = utc_now_iso()
        conn = self._db.connect()
        try:
            conn.execute(
                """
                INSERT INTO meetings(id, title, transcript, created_at, started_at, status, source_text)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    meeting_id,
                    filename,
                    transcript,
                    now,
                    now,
                    "pending",
                    transcript,
                ),
            )
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
                    assignee_id = self._get_or_create_user(conn, assignee_name)
                conn.execute(
                    """
                    INSERT INTO tasks(
                        id, meeting_id, summary, description, issue_type, priority,
                        story_points, assignee_id, labels, status, source_quote,
                        created_at, updated_at
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(uuid.uuid4()),
                        meeting_id,
                        task.summary,
                        task.description,
                        task.issue_type.value,
                        task.priority.value,
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
        self._update_meeting_status(meeting_id)
        return meeting_id, run_id

    # --- Internal helpers ------------------------------------------------
    def _update_meeting_status(self, meeting_id: str) -> None:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS pending FROM tasks WHERE meeting_id = ? AND status = 'draft'",
                (meeting_id,),
            ).fetchone()
            new_status = "pending" if row and row["pending"] else "processed"
            conn.execute(
                "UPDATE meetings SET status = ? WHERE id = ?",
                (new_status, meeting_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _get_or_create_user(self, conn: sqlite3.Connection, display_name: str) -> str:
        row = conn.execute(
            "SELECT id FROM users WHERE display_name = ?",
            (display_name,),
        ).fetchone()
        if row:
            return row["id"]
        user_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users(id, display_name) VALUES(?, ?)",
            (user_id, display_name),
        )
        return user_id


__all__ = [
    "SqliteMeetingsRepository",
    "TASK_STATUSES",
    "ISSUE_TYPES",
    "PRIORITIES",
]
