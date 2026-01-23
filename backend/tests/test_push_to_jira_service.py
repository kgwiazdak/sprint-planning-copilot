from __future__ import annotations

import pytest

from backend.application.services.push_to_jira import PushTasksToJiraService
from backend.infrastructure.jira import JiraClientError, JiraIssue


class FakeRepo:
    def __init__(self, tasks: list[dict], users: dict[str, dict] | None = None, meetings: dict[str, dict] | None = None) -> None:
        self._tasks = tasks
        self.marked: list[tuple[str, str, str | None]] = []
        self.users = users or {}
        self.meetings = meetings or {}

    def get_tasks_by_ids(self, ids, *, owner_id: str):
        return [task for task in self._tasks if task["id"] in ids]

    def mark_task_pushed_to_jira(self, task_id: str, *, issue_key: str, issue_url: str | None, owner_id: str) -> None:
        self.marked.append((task_id, issue_key, issue_url))

    def get_user(self, user_id: str, *, owner_id: str):
        return self.users.get(user_id)

    def update_user_jira_account(self, user_id: str, account_id: str, *, owner_id: str) -> None:
        if user_id in self.users:
            self.users[user_id]["jiraAccountId"] = account_id

    def get_meeting(self, meeting_id: str, *, owner_id: str):
        return self.meetings.get(meeting_id)


class FakeJiraClient:
    def __init__(self, project_key: str | None = "SCRUM") -> None:
        self._project_key = project_key
        self.calls: list[dict] = []
        self.counter = 0
        self.lookup: dict[str, str] = {}

    def create_issue(self, **payload):
        self.counter += 1
        self.calls.append(payload)
        key = f"SCRUM-{self.counter}"
        return JiraIssue(key=key, url=f"https://example.atlassian.net/browse/{key}")

    def find_user_account_id(self, display_name: str) -> str | None:
        return self.lookup.get(display_name)

    @property
    def default_project_key(self) -> str | None:
        return self._project_key


def test_pushes_tasks_and_marks_repository():
    meeting_id = "meeting-1"
    task = {
        "id": "task-1",
        "summary": "Implement login",
        "description": "Need SSO",
        "issueType": "Story",
        "priority": "High",
        "labels": ["backend"],
        "storyPoints": 5,
        "assigneeAccountId": "user-123",
        "sourceQuote": "We must finish login",
        "meetingId": meeting_id,
    }
    repo = FakeRepo([task], meetings={meeting_id: {"id": meeting_id, "projectKey": "SCRUM"}})
    jira = FakeJiraClient()
    service = PushTasksToJiraService(repo=repo, jira_client=jira)

    result = service.push([task["id"]], owner_id="owner-1")

    assert result.pushed == 1
    assert result.skipped == 0
    assert repo.marked == [("task-1", "SCRUM-1", "https://example.atlassian.net/browse/SCRUM-1")]
    assert jira.calls[0]["summary"] == "Implement login"
    assert jira.calls[0]["assignee_account_id"] == "user-123"


def test_skips_tasks_already_linked_to_jira():
    meeting_id = "meeting-2"
    task = {
        "id": "task-1",
        "summary": "Done task",
        "jiraIssueKey": "SCRUM-9",
        "meetingId": meeting_id,
    }
    repo = FakeRepo([task], meetings={meeting_id: {"id": meeting_id, "projectKey": "SCRUM"}})
    jira = FakeJiraClient()
    service = PushTasksToJiraService(repo=repo, jira_client=jira)

    result = service.push([task["id"]], owner_id="owner-1")

    assert result.pushed == 0
    assert result.skipped == 1
    assert repo.marked == []
    assert jira.calls == []


def test_raises_when_jira_rejects_request():
    class FailJiraClient(FakeJiraClient):
        def create_issue(self, **payload):
            raise JiraClientError("boom")

    task = {"id": "task-1", "summary": "Broken"}
    repo = FakeRepo([task])
    jira = FailJiraClient()
    service = PushTasksToJiraService(repo=repo, jira_client=jira)

    with pytest.raises(JiraClientError):
        service.push([task["id"]], owner_id="owner-1", project_key="PRJ")
    assert repo.marked == []


def test_sanitizes_labels_before_pushing():
    meeting_id = "meeting-3"
    task = {
        "id": "task-1",
        "summary": "Label cleanup",
        "labels": ["Data ingestion", " model drift ", "QA&Ops"],
        "meetingId": meeting_id,
    }
    repo = FakeRepo([task], meetings={meeting_id: {"id": meeting_id, "projectKey": "SCRUM"}})
    jira = FakeJiraClient()
    service = PushTasksToJiraService(repo=repo, jira_client=jira)

    service.push([task["id"]], owner_id="owner-1")

    assert jira.calls[0]["labels"] == ["data-ingestion", "model-drift", "qa-ops"]


def test_looks_up_jira_account_when_missing(tmp_path=None):
    meeting_id = "meeting-4"
    task = {
        "id": "task-2",
        "summary": "Assign via lookup",
        "assigneeId": "user-42",
        "meetingId": meeting_id,
    }
    users = {
        "user-42": {"id": "user-42", "displayName": "Sam Carter", "jiraAccountId": None},
    }
    repo = FakeRepo([task], users=users, meetings={meeting_id: {"id": meeting_id, "projectKey": "SCRUM"}})
    jira = FakeJiraClient()
    jira.lookup["Sam Carter"] = "jira-user-123"
    service = PushTasksToJiraService(repo=repo, jira_client=jira)

    service.push([task["id"]], owner_id="owner-1")

    assert repo.users["user-42"]["jiraAccountId"] == "jira-user-123"
    assert jira.calls[0]["assignee_account_id"] == "jira-user-123"


def test_uses_explicit_project_when_provided():
    meeting_id = "meeting-5"
    task = {"id": "task-3", "summary": "Explicit project", "meetingId": meeting_id}
    repo = FakeRepo([task], meetings={meeting_id: {"id": meeting_id, "projectKey": "DEF"}})
    jira = FakeJiraClient(project_key="DEF")
    service = PushTasksToJiraService(repo=repo, jira_client=jira)

    service.push([task["id"]], owner_id="owner-1", project_key="ALT")

    assert jira.calls[0]["project_key"] == "ALT"


def test_raises_when_no_project_available():
    meeting_id = "meeting-6"
    task = {"id": "task-4", "summary": "No project key", "meetingId": meeting_id}
    repo = FakeRepo([task], meetings={meeting_id: {"id": meeting_id, "projectKey": None}})
    jira = FakeJiraClient(project_key=None)
    service = PushTasksToJiraService(repo=repo, jira_client=jira)

    with pytest.raises(JiraClientError):
        service.push([task["id"]], owner_id="owner-1")
