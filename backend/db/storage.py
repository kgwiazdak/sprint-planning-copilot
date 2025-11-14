from __future__ import annotations

import datetime
import json
import os
import pathlib
import sqlite3
import uuid
from typing import Any, Iterable, Optional

DB_URL = os.getenv("DB_URL", "sqlite:///./app.db")

TASK_STATUSES = ("draft", "approved", "rejected")
ISSUE_TYPES = ("Story", "Task", "Bug", "Spike")
PRIORITIES = ("Low", "Medium", "High")


def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()


class SqliteMeetingsRepository:
    """SQLite-backed repository exposing CRUD helpers for meetings and tasks."""

    def __init__(self, db_url: str | None = None) -> None:
        self._db_url = db_url or DB_URL
        if not self._db_url.startswith("sqlite"):
            raise ValueError("Only sqlite URLs are supported in this adapter.")
        self._db_path = self._db_url.split("///")[-1]
        pathlib.Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_db(self) -> None:
        conn = self._connect()
        try:
            self._init_schema(conn)
            self._seed_if_needed(conn)
        finally:
            conn.close()

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meetings(
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                transcript TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                status TEXT DEFAULT 'pending',
                source_url TEXT,
                source_text TEXT
            )
        """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS extraction_runs(
                id TEXT PRIMARY KEY,
                meeting_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
            )
        """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks(
                id TEXT PRIMARY KEY,
                meeting_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                description TEXT,
                issue_type TEXT NOT NULL,
                priority TEXT NOT NULL,
                story_points INTEGER,
                assignee_id TEXT,
                labels TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                source_quote TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
            )
        """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users(
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                email TEXT
            )
        """
        )
        conn.commit()

    def _seed_if_needed(self, conn: sqlite3.Connection) -> None:
        cur = conn.cursor()
        result = cur.execute("SELECT COUNT(*) AS total FROM meetings").fetchone()
        if result and result["total"]:
            return

        now = _now_iso()
        users = [
            ("u1", "Alex Rivera", "alex@example.com"),
            ("u2", "Jordan Hale", "jordan@example.com"),
            ("u3", "Sasha Patel", "sasha@example.com"),
        ]
        cur.executemany(
            "INSERT INTO users(id, display_name, email) VALUES(?,?,?)",
            users,
        )

        meetings = [
            {
                "id": "m1",
                "title": "Sprint Planning 42",
                "started_at": (datetime.datetime.utcnow() - datetime.timedelta(days=2)).isoformat(),
                "status": "pending",
                "source_text": "Sprint planning discussion with backlog refinement.",
                "tasks": [
                    {
                        "summary": "Refine onboarding checklist",
                        "description": "Update checklist with latest compliance items.",
                        "issue_type": "Task",
                        "priority": "Medium",
                        "story_points": 3,
                        "assignee_id": "u1",
                        "labels": ["onboarding", "compliance"],
                        "status": "draft",
                        "source_quote": "Need to ensure the onboarding doc is updated for Q3 audit.",
                    },
                    {
                        "summary": "Add audit logging to payments",
                        "description": "Capture all write operations for PCI review.",
                        "issue_type": "Story",
                        "priority": "High",
                        "story_points": 5,
                        "assignee_id": "u2",
                        "labels": ["payments", "security"],
                        "status": "approved",
                        "source_quote": "Payments service needs better observability before launch.",
                    },
                ],
            },
            {
                "id": "m2",
                "title": "Incident Retro",
                "started_at": (datetime.datetime.utcnow() - datetime.timedelta(days=5)).isoformat(),
                "status": "pending",
                "source_text": "Retro covering last week's outage.",
                "tasks": [
                    {
                        "summary": "Automate failover smoke tests",
                        "description": "Add scheduled chaos tests to staging.",
                        "issue_type": "Spike",
                        "priority": "High",
                        "story_points": 2,
                        "assignee_id": "u3",
                        "labels": ["reliability"],
                        "status": "draft",
                        "source_quote": "We missed the failover regression before the outage.",
                    },
                    {
                        "summary": "Document incident response playbook",
                        "description": "Capture the mitigation timeline and contacts.",
                        "issue_type": "Task",
                        "priority": "Medium",
                        "assignee_id": "u1",
                        "labels": ["documentation"],
                        "status": "rejected",
                        "source_quote": "Let's fold the lessons into the official playbook.",
                    },
                ],
            },
            {
                "id": "m3",
                "title": "Roadmap Sync",
                "started_at": (datetime.datetime.utcnow() - datetime.timedelta(days=8)).isoformat(),
                "status": "processed",
                "source_text": "Quarterly roadmap prioritization.",
                "tasks": [
                    {
                        "summary": "Evaluate feature flag rollout plan",
                        "description": "Compare LaunchDarkly vs homegrown toggles.",
                        "issue_type": "Story",
                        "priority": "Medium",
                        "assignee_id": "u2",
                        "labels": ["feature-flags"],
                        "status": "approved",
                        "source_quote": "Need a decision before the next release train.",
                    }
                ],
            },
        ]

        for meeting in meetings:
            cur.execute(
                """
                INSERT INTO meetings(id, title, transcript, created_at, started_at, status, source_text)
                VALUES(?,?,?,?,?,?,?)
            """,
                (
                    meeting["id"],
                    meeting["title"],
                    meeting["source_text"],
                    now,
                    meeting["started_at"],
                    meeting["status"],
                    meeting["source_text"],
                ),
            )
            for task in meeting["tasks"]:
                task_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO tasks(
                        id, meeting_id, summary, description, issue_type, priority,
                        story_points, assignee_id, labels, status, source_quote,
                        created_at, updated_at
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                    (
                        task_id,
                        meeting["id"],
                        task["summary"],
                        task["description"],
                        task["issue_type"],
                        task["priority"],
                        task.get("story_points"),
                        task.get("assignee_id"),
                        json.dumps(task.get("labels", [])),
                        task["status"],
                        task.get("source_quote"),
                        now,
                        now,
                    ),
                )
        conn.commit()
        for meeting in meetings:
            self._update_meeting_status(meeting["id"])

    def _serialize_meeting_row(self, row: sqlite3.Row) -> dict[str, Any]:
        started = row["started_at"] or row["created_at"]
        return {
            "id": row["id"],
            "title": row["title"],
            "startedAt": started,
            "status": row["status"] or "pending",
            "draftTaskCount": row["draft_count"],
        }

    def _serialize_task_row(self, row: sqlite3.Row) -> dict[str, Any]:
        labels = json.loads(row["labels"]) if row["labels"] else []
        return {
            "id": row["id"],
            "meetingId": row["meeting_id"],
            "summary": row["summary"],
            "description": row["description"] or "",
            "issueType": row["issue_type"],
            "priority": row["priority"],
            "storyPoints": row["story_points"],
            "assigneeId": row["assignee_id"],
            "labels": labels,
            "status": row["status"],
            "sourceQuote": row["source_quote"],
        }

    def list_meetings(self) -> list[dict[str, Any]]:
        conn = self._connect()
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
            return [self._serialize_meeting_row(row) for row in rows]
        finally:
            conn.close()

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        conn = self._connect()
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
            return self._serialize_meeting_row(row)
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
        now = _now_iso()
        conn = self._connect()
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
        conn = self._connect()
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
        return self.get_meeting(meeting_id)

    def delete_meeting(self, meeting_id: str) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list_tasks(
        self,
        *,
        meeting_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
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
            return [self._serialize_task_row(row) for row in rows]
        finally:
            conn.close()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            return self._serialize_task_row(row)
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
        params.append(_now_iso())
        params.append(task_id)
        conn = self._connect()
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
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in ids)
            params = [status, _now_iso(), *ids]
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
        conn = self._connect()
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

    def _update_meeting_status(self, meeting_id: str) -> None:
        conn = self._connect()
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

    def store_meeting_and_result(
        self,
        filename: str,
        transcript: str,
        result_model,
        meeting_id: Optional[str] = None,
    ) -> tuple[str, str]:
        meeting_id = meeting_id or str(uuid.uuid4())
        now = _now_iso()
        conn = self._connect()
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


def store_meeting_and_result(
    filename: str,
    transcript: str,
    result_model,
    meeting_id: Optional[str] = None,
):
    repo = SqliteMeetingsRepository()
    return repo.store_meeting_and_result(filename, transcript, result_model, meeting_id=meeting_id)
