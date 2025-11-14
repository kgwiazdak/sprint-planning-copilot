import datetime
import json
import os
import pathlib
import sqlite3
import uuid
from typing import Optional

DB_URL = os.getenv("DB_URL", "sqlite:///./app.db")


class SqliteMeetingsRepository:
    """Simple SQLite-backed repository for meetings and extraction runs."""

    def __init__(self, db_url: str | None = None) -> None:
        self._db_url = db_url or DB_URL

    def _ensure_db(self):
        if self._db_url.startswith("sqlite"):
            db_file = self._db_url.split("///")[-1]
        else:
            db_file = "app.db"
        need_init = not pathlib.Path(db_file).exists()
        conn = sqlite3.connect(db_file)
        if need_init:
            cur = conn.cursor()
            cur.execute(
                """CREATE TABLE IF NOT EXISTS meetings(
            id TEXT PRIMARY KEY, title TEXT, transcript TEXT, created_at TEXT
        )"""
            )
            cur.execute(
                """CREATE TABLE IF NOT EXISTS extraction_runs(
            id TEXT PRIMARY KEY, meeting_id TEXT, payload_json TEXT, created_at TEXT
        )"""
            )
            conn.commit()
        return conn

    def store_meeting_and_result(
        self, filename: str, transcript: str, result_model, meeting_id: Optional[str] = None
    ):
        conn = self._ensure_db()
        cur = conn.cursor()
        meeting_id = meeting_id or str(uuid.uuid4())
        now = datetime.datetime.utcnow().isoformat()
        cur.execute(
            "INSERT INTO meetings(id, title, transcript, created_at) VALUES(?,?,?,?)",
            (meeting_id, filename, transcript, now),
        )
        run_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO extraction_runs(id, meeting_id, payload_json, created_at) VALUES(?,?,?,?)",
            (run_id, meeting_id, json.dumps(result_model.dict()), now),
        )
        conn.commit()
        conn.close()
        return meeting_id, run_id


def store_meeting_and_result(filename: str, transcript: str, result_model, meeting_id: Optional[str] = None):
    repo = SqliteMeetingsRepository()
    return repo.store_meeting_and_result(filename, transcript, result_model, meeting_id=meeting_id)
