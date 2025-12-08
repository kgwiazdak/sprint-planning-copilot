from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

from backend.domain.ports import MeetingsRepositoryPort
from backend.infrastructure.jira import JiraClient, JiraClientError, JiraIssue

logger = logging.getLogger(__name__)


@dataclass
class PushTasksResult:
    total: int
    pushed: int
    skipped: int


class PushTasksToJiraService:
    """Pushes approved tasks to Jira and updates local persistence."""

    def __init__(self, *, repo: MeetingsRepositoryPort, jira_client: JiraClient) -> None:
        self._repo = repo
        self._jira = jira_client

    def push(self, task_ids: Iterable[str], *, owner_id: str, project_key: str | None = None) -> PushTasksResult:
        ids = [task_id for task_id in task_ids if task_id]
        if not ids:
            return PushTasksResult(total=0, pushed=0, skipped=0)

        tasks = self._repo.get_tasks_by_ids(ids, owner_id=owner_id)
        target_project = project_key or self._jira.default_project_key
        if not target_project:
            raise JiraClientError("Jira project key is required to push tasks.")
        pushed = 0
        skipped = 0
        for task in tasks:
            if task.get("jiraIssueKey"):
                logger.info("Skipping task %s; already pushed as %s", task["id"], task["jiraIssueKey"])
                skipped += 1
                continue
            assignee_account_id = task.get("assigneeAccountId")
            if not assignee_account_id:
                assignee_account_id = self._resolve_assignee_account(task, owner_id=owner_id)
            issue = self._create_issue(task, assignee_account_id=assignee_account_id, project_key=target_project)
            self._repo.mark_task_pushed_to_jira(
                task["id"],
                issue_key=issue.key,
                issue_url=issue.url,
                owner_id=owner_id,
            )
            pushed += 1
        return PushTasksResult(total=len(tasks), pushed=pushed, skipped=skipped)

    def _create_issue(self, task: dict, *, assignee_account_id: str | None, project_key: str) -> JiraIssue:
        try:
            labels = self._sanitize_labels(task.get("labels") or [])
            return self._jira.create_issue(
                summary=task.get("summary", ""),
                description=task.get("description"),
                issue_type=task.get("issueType", "Task"),
                priority=task.get("priority", "Medium"),
                labels=labels,
                assignee_account_id=assignee_account_id,
                story_points=task.get("storyPoints"),
                source_quote=task.get("sourceQuote"),
                project_key=project_key,
            )
        except JiraClientError:
            logger.exception("Failed to push task %s to Jira", task.get("id"))
            raise

    @staticmethod
    def _sanitize_labels(labels: list[str]) -> list[str]:
        sanitized: list[str] = []
        for label in labels:
            if not label:
                continue
            slug = re.sub(r"[^A-Za-z0-9_-]+", "-", label.strip().lower())
            slug = slug.strip("-_")
            if slug:
                sanitized.append(slug[:255])
        return sanitized

    def _resolve_assignee_account(self, task: dict, *, owner_id: str) -> str | None:
        user_id = task.get("assigneeId")
        if not user_id:
            return None
        user = self._repo.get_user(user_id, owner_id=owner_id)
        if not user:
            return None
        account_id = user.get("jiraAccountId")
        if account_id:
            return account_id
        display_name = user.get("displayName")
        if not display_name:
            return None
        try:
            account_id = self._jira.find_user_account_id(display_name)
        except JiraClientError:
            logger.exception("Failed to resolve Jira account for %s", display_name)
            return None
        if account_id:
            self._repo.update_user_jira_account(user_id, account_id, owner_id=owner_id)
        return account_id
