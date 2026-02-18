from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from backend.infrastructure.jira import JiraClientError, JiraIssue, JiraProject

logger = logging.getLogger(__name__)


@dataclass
class MCPAtlassianClient:
    server_url: str
    timeout_seconds: float = 30.0

    def list_projects(self, *, max_results: int = 50) -> list[JiraProject]:
        payload = self._call_tool("jira_list_projects", {"max_results": max_results})
        rows = payload.get("projects", [])
        projects: list[JiraProject] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "").strip()
            name = str(row.get("name") or "").strip()
            if key and name:
                projects.append(JiraProject(key=key, name=name))
        return projects

    def find_user_account_id(self, display_name: str) -> str | None:
        payload = self._call_tool("jira_find_user_account_id", {"display_name": display_name})
        value = payload.get("accountId")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def create_issue(
        self,
        *,
        summary: str,
        description: str,
        issue_type: str,
        assignee_account_id: str | None,
        priority: str,
        story_points: int | None,
        labels: list[str] | None = None,
        links: list[str] | None = None,
        quotes: list[str] | None = None,
        project_key: str | None = None,
    ) -> JiraIssue:
        payload = self._call_tool(
            "jira_create_issue",
            {
                "summary": summary,
                "description": description,
                "issue_type": issue_type,
                "assignee_account_id": assignee_account_id,
                "priority": priority,
                "story_points": story_points,
                "labels": labels or [],
                "links": links or [],
                "quotes": quotes or [],
                "project_key": project_key,
            },
        )
        key = str(payload.get("key") or "").strip()
        if not key:
            raise JiraClientError(f"MCP Jira did not return issue key: {payload}")
        url = payload.get("url")
        return JiraIssue(key=key, url=url if isinstance(url, str) else None)

    def list_confluence_spaces(self, *, limit: int = 25) -> list[dict[str, str]]:
        payload = self._call_tool("confluence_list_spaces", {"limit": limit})
        rows = payload.get("spaces", [])
        out: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": str(row.get("id") or ""),
                    "key": str(row.get("key") or ""),
                    "name": str(row.get("name") or ""),
                    "type": str(row.get("type") or ""),
                }
            )
        return out

    def search_confluence_pages(
        self,
        *,
        limit: int = 25,
        space_key: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        payload = self._call_tool(
            "confluence_search_pages",
            {"limit": limit, "space_key": space_key, "query": query},
        )
        rows = payload.get("pages", [])
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": str(row.get("id") or ""),
                    "title": str(row.get("title") or ""),
                    "spaceKey": str(row.get("spaceKey") or ""),
                    "spaceName": str(row.get("spaceName") or ""),
                    "webui": str(row.get("webui") or ""),
                    "content": str(row.get("content") or ""),
                    "version": int(row.get("version") or 0),
                }
            )
        return out

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return anyio.run(self._call_tool_async, name, arguments)

    async def _call_tool_async(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            async with streamablehttp_client(
                self.server_url,
                timeout=self.timeout_seconds,
                sse_read_timeout=self.timeout_seconds,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(name=name, arguments=arguments)
        except Exception as exc:
            raise JiraClientError(f"MCP call failed for tool '{name}': {exc}") from exc

        if result.isError:
            payload = self._extract_payload(result.content, result.structuredContent)
            raise JiraClientError(f"MCP tool '{name}' returned error: {payload}")

        payload = self._extract_payload(result.content, result.structuredContent)
        if not isinstance(payload, dict):
            raise JiraClientError(f"MCP tool '{name}' returned non-object payload: {payload}")
        return payload

    @staticmethod
    def _extract_payload(content: Any, structured: Any) -> Any:
        if isinstance(structured, dict):
            return structured
        if isinstance(content, list):
            texts: list[str] = []
            for item in content:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    texts.append(text)
            if texts:
                merged = "\n".join(texts).strip()
                if merged:
                    try:
                        return json.loads(merged)
                    except json.JSONDecodeError:
                        return {"text": merged}
        if isinstance(structured, str):
            try:
                return json.loads(structured)
            except json.JSONDecodeError:
                return {"text": structured}
        return {"content": str(content), "structured": str(structured)}
