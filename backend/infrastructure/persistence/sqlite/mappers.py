from __future__ import annotations

import json
from typing import Any

from .database import Meeting, Task, User


def serialize_meeting_row(meeting: Meeting, draft_count: int = 0) -> dict[str, Any]:
    started = meeting.started_at or meeting.created_at
    return {
        "id": meeting.id,
        "title": meeting.title,
        "startedAt": started,
        "status": meeting.status or "pending",
        "draftTaskCount": draft_count,
        "projectKey": meeting.project_key,
    }


def serialize_task_row(task: Task, assignee: User | None = None) -> dict[str, Any]:
    labels = json.loads(task.labels) if task.labels else []
    return {
        "id": task.id,
        "meetingId": task.meeting_id,
        "summary": task.summary,
        "description": task.description or "",
        "issueType": task.issue_type,
        "priority": task.priority,
        "storyPoints": task.story_points,
        "assigneeId": task.assignee_id,
        "assigneeName": assignee.display_name if assignee else None,
        "assigneeAccountId": assignee.jira_account_id if assignee else None,
        "labels": labels,
        "status": task.status,
        "sourceQuote": task.source_quote,
        "jiraIssueKey": task.jira_issue_key,
        "jiraIssueUrl": task.jira_issue_url,
        "pushedToJiraAt": task.pushed_to_jira_at,
    }
