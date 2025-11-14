from __future__ import annotations

import json
import sqlite3
from typing import Any


def serialize_meeting_row(row: sqlite3.Row) -> dict[str, Any]:
    started = row["started_at"] or row["created_at"]
    return {
        "id": row["id"],
        "title": row["title"],
        "startedAt": started,
        "status": row["status"] or "pending",
        "draftTaskCount": row["draft_count"],
    }


def serialize_task_row(row: sqlite3.Row) -> dict[str, Any]:
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
