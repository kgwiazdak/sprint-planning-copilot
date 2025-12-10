from __future__ import annotations

import datetime
import pathlib

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

from .constants import DEFAULT_DB_URL


Base = declarative_base()


def utc_now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    transcript = Column(Text)
    created_at = Column(String, nullable=False)
    started_at = Column(String)
    status = Column(String, default="queued")
    source_url = Column(String)
    source_text = Column(Text)
    project_key = Column(String)
    owner_id = Column(String)

    tasks = relationship(
        "Task",
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    runs = relationship(
        "ExtractionRun",
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    meeting_id = Column(String, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    summary = Column(Text, nullable=False)
    description = Column(Text)
    issue_type = Column(String, nullable=False)
    priority = Column(String, nullable=False)
    story_points = Column(Integer)
    assignee_id = Column(String, ForeignKey("users.id"), nullable=True)
    labels = Column(Text)
    status = Column(String, nullable=False, default="draft")
    source_quote = Column(Text)
    jira_issue_key = Column(String)
    jira_issue_url = Column(String)
    pushed_to_jira_at = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    owner_id = Column(String)

    meeting = relationship("Meeting", back_populates="tasks")
    assignee = relationship("User", back_populates="tasks", foreign_keys=[assignee_id])


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    display_name = Column(String, nullable=False)
    email = Column(String)
    jira_account_id = Column(String)
    voice_sample_path = Column(String)
    owner_id = Column(String)

    tasks = relationship("Task", back_populates="assignee", passive_deletes=True)


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id = Column(String, primary_key=True)
    meeting_id = Column(String, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    payload_json = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)

    meeting = relationship("Meeting", back_populates="runs")


class SqliteDatabase:
    """Manages the SQLAlchemy engine, sessions, and schema creation."""

    def __init__(self, url: str | None = None) -> None:
        self._db_url = url or DEFAULT_DB_URL
        if not self._db_url.startswith("sqlite"):
            raise ValueError("Only sqlite URLs are supported.")
        db_path = self._db_url.split("///")[-1]
        pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._engine = create_engine(self._db_url, future=True, connect_args={"check_same_thread": False})
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False, autoflush=False)

        # Ensure foreign key constraints are enforced for SQLite.
        @event.listens_for(self._engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self._engine)
        self._ensure_columns()

    def session(self) -> Session:
        return self._session_factory()

    def _ensure_columns(self) -> None:
        """Backfill columns that may be missing in existing databases."""
        with self._engine.begin() as conn:
            self._add_column_if_missing(conn, "tasks", "jira_issue_key", "TEXT")
            self._add_column_if_missing(conn, "tasks", "jira_issue_url", "TEXT")
            self._add_column_if_missing(conn, "tasks", "pushed_to_jira_at", "TEXT")
            self._add_column_if_missing(conn, "tasks", "owner_id", "TEXT")
            self._add_column_if_missing(conn, "meetings", "project_key", "TEXT")
            self._add_column_if_missing(conn, "meetings", "owner_id", "TEXT")
            self._add_column_if_missing(conn, "users", "jira_account_id", "TEXT")
            self._add_column_if_missing(conn, "users", "voice_sample_path", "TEXT")
            self._add_column_if_missing(conn, "users", "owner_id", "TEXT")

    @staticmethod
    def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
