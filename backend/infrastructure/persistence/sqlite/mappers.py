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
        "projectKey": row["project_key"] if "project_key" in row.keys() else None,
    }


def serialize_task_row(row: sqlite3.Row) -> dict[str, Any]:
    labels = json.loads(row["labels"]) if row["labels"] else []
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    assignee_account = None
    if "assignee_jira_account_id" in keys:
        assignee_account = row["assignee_jira_account_id"]
    elif "jira_account_id" in keys:
        assignee_account = row["jira_account_id"]
    assignee_name = None
    if "assignee_display_name" in keys:
        assignee_name = row["assignee_display_name"]
    return {
        "id": row["id"],
        "meetingId": row["meeting_id"],
        "summary": row["summary"],
        "description": row["description"] or "",
        "issueType": row["issue_type"],
        "priority": row["priority"],
        "storyPoints": row["story_points"],
        "assigneeId": row["assignee_id"],
        "assigneeName": assignee_name,
        "assigneeAccountId": assignee_account,
        "labels": labels,
        "status": row["status"],
        "sourceQuote": row["source_quote"],
        "jiraIssueKey": row["jira_issue_key"] if "jira_issue_key" in keys else None,
        "jiraIssueUrl": row["jira_issue_url"] if "jira_issue_url" in keys else None,
        "pushedToJiraAt": row["pushed_to_jira_at"] if "pushed_to_jira_at" in keys else None,
    }
