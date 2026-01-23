from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


class JiraClientError(RuntimeError):
    """Raised when the Jira API rejects a request or cannot be reached."""


@dataclass
class JiraIssue:
    key: str
    url: str


@dataclass
class JiraProject:
    key: str
    name: str


class JiraClient:
    """Tiny Jira REST API adapter that creates backlog items from approved tasks."""

    def __init__(
            self,
            *,
            base_url: str,
            email: str | None = None,
            api_token: str | None = None,
            bearer_token: str | None = None,
            project_key: str | None = None,
            story_points_field: str | None = None,
            timeout: float = 20.0,
    ) -> None:
        if not base_url:
            raise ValueError("Jira client requires base_url.")
        if not bearer_token and (not email or not api_token):
            raise ValueError("Jira client requires email and api_token unless bearer_token is provided.")
        self._base_url = base_url.rstrip("/")
        self._api_base = f"{self._base_url}/rest/api/3"
        self._project_key = project_key
        self._story_points_field = story_points_field
        if bearer_token:
            self._auth_header = f"Bearer {bearer_token}"
        else:
            token = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("utf-8")
            self._auth_header = f"Basic {token}"
        self._timeout = timeout

    def create_issue(
            self,
            *,
            summary: str,
            description: str | None,
            issue_type: str,
            priority: str,
            labels: list[str] | None,
            assignee_account_id: str | None,
            story_points: int | None,
            source_quote: str | None,
            project_key: str | None = None,
    ) -> JiraIssue:
        target_project = project_key or self._project_key
        if not target_project:
            raise JiraClientError("Jira project key is required to create issues.")
        payload = {
            "fields": self._build_fields(
                summary=summary,
                description=description,
                issue_type=issue_type,
                priority=priority,
                labels=labels,
                assignee_account_id=assignee_account_id,
                story_points=story_points,
                source_quote=source_quote,
                project_key=target_project,
            )
        }
        data = self._request("POST", "/issue", payload)
        key = data.get("key")
        if not key:
            raise JiraClientError(f"Jira API response did not include an issue key: {data}")
        issue_url = f"{self._base_url}/browse/{key}"
        return JiraIssue(key=key, url=issue_url)

    def _build_fields(
            self,
            *,
            summary: str,
            description: str | None,
            issue_type: str,
            priority: str,
            labels: list[str] | None,
            assignee_account_id: str | None,
            story_points: int | None,
            source_quote: str | None,
            project_key: str,
    ) -> dict[str, Any]:
        summary_text = (summary or "").strip() or "Untitled task"
        fields: dict[str, Any] = {
            "summary": summary_text[:254],
            "project": {"key": project_key},
            "issuetype": {"name": issue_type or "Task"},
            "priority": {"name": priority or "Medium"},
        }
        description_body = self._build_description(description, source_quote)
        if description_body:
            fields["description"] = description_body
        if labels:
            fields["labels"] = labels
        if assignee_account_id:
            fields["assignee"] = {"accountId": assignee_account_id}
        if story_points is not None and self._story_points_field:
            fields[self._story_points_field] = story_points
        return fields

    def _build_description(self, description: str | None, source_quote: str | None) -> dict[str, Any] | None:
        paragraphs = []
        text = (description or "").strip()
        if text:
            for block in text.splitlines():
                paragraphs.append(self._paragraph(block))
        if source_quote:
            paragraphs.append(
                {
                    "type": "blockquote",
                    "content": [
                        self._paragraph(source_quote.strip() or "Original quote unavailable."),
                    ],
                }
            )
        if not paragraphs:
            return None
        return {"type": "doc", "version": 1, "content": paragraphs}

    @staticmethod
    def _paragraph(text: str) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        cleaned = text.strip()
        if cleaned:
            content.append({"type": "text", "text": cleaned})
        return {"type": "paragraph", "content": content}

    def _request(self, method: str, path: str, payload: dict[str, Any] | None) -> Any:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = request.Request(
            f"{self._api_base}{path}",
            data=body,
            headers={
                "Authorization": self._auth_header,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self._timeout) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data) if data else {}
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            message = details or exc.reason or f"HTTP {exc.code}"
            raise JiraClientError(f"Jira API error: {message}") from exc
        except error.URLError as exc:
            raise JiraClientError(f"Failed to reach Jira: {exc.reason}") from exc

    def find_user_account_id(self, display_name: str) -> str | None:
        query = parse.urlencode({"query": display_name, "maxResults": 1})
        data = self._request("GET", f"/user/search?{query}", None)
        if isinstance(data, list) and data:
            return data[0].get("accountId")
        return None

    def list_projects(self, *, max_results: int = 50) -> list[JiraProject]:
        query = parse.urlencode({"maxResults": max_results, "orderBy": "key"})
        data = self._request("GET", f"/project/search?{query}", None)
        projects: list[JiraProject] = []
        for item in data.get("values", []) if isinstance(data, dict) else []:
            key = item.get("key")
            name = item.get("name")
            if key and name:
                projects.append(JiraProject(key=key, name=name))
        return projects

    @property
    def default_project_key(self) -> str | None:
        return self._project_key
