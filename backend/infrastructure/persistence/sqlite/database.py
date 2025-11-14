from __future__ import annotations

import datetime
import pathlib
import sqlite3

from .constants import DEFAULT_DB_URL


def utc_now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()


class SqliteDatabase:
    """Manages the sqlite connection lifecycle and schema creation."""

    def __init__(self, url: str | None = None) -> None:
        self._db_url = url or DEFAULT_DB_URL
        if not self._db_url.startswith("sqlite"):
            raise ValueError("Only sqlite URLs are supported.")
        self._db_path = self._db_url.split("///")[-1]
        pathlib.Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        conn = self.connect()
        try:
            _init_schema(conn)
        finally:
            conn.close()


def _init_schema(conn: sqlite3.Connection) -> None:
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
