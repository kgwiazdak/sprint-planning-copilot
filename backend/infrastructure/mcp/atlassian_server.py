from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

from backend.infrastructure.jira import JiraClient, JiraClientError


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


_HOST = _env("MCP_SERVER_HOST", "0.0.0.0") or "0.0.0.0"
_PORT = int(_env("MCP_SERVER_PORT", "8111") or "8111")

mcp = FastMCP("atlassian-mcp", host=_HOST, port=_PORT, streamable_http_path="/mcp")


def _jira_client() -> JiraClient:
    base_url = _env("JIRA_BASE_URL")
    email = _env("JIRA_EMAIL")
    api_token = _env("JIRA_API_TOKEN")
    if not base_url or not email or not api_token:
        raise JiraClientError("MCP Jira server is not configured: set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN.")
    return JiraClient(
        base_url=base_url,
        browse_base_url=base_url,
        email=email,
        api_token=api_token,
        project_key=_env("JIRA_PROJECT_KEY"),
        story_points_field=_env("JIRA_STORY_POINTS_FIELD"),
    )


def _confluence_base_url() -> str:
    base_url = _env("CONFLUENCE_BASE_URL") or _env("JIRA_BASE_URL")
    if not base_url:
        raise RuntimeError("Confluence base URL is not configured.")
    return base_url.rstrip("/")


def _confluence_auth_header() -> str:
    email = _env("CONFLUENCE_EMAIL") or _env("JIRA_EMAIL")
    api_token = _env("CONFLUENCE_API_TOKEN") or _env("JIRA_API_TOKEN")
    if not email or not api_token:
        raise RuntimeError("Confluence credentials are not configured.")
    raw = f"{email}:{api_token}".encode("utf-8")
    import base64
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _confluence_get_json(path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    base_url = _confluence_base_url()
    auth = _confluence_auth_header()
    query_str = urllib.parse.urlencode(query or {})
    suffix = f"?{query_str}" if query_str else ""
    url = f"{base_url}{path}{suffix}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": auth, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Confluence API error: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Confluence unreachable: {exc.reason}") from exc
    return payload if isinstance(payload, dict) else {}


@mcp.tool()
def jira_list_projects(max_results: int = 50) -> dict[str, Any]:
    client = _jira_client()
    projects = client.list_projects(max_results=max_results)
    return {"projects": [{"key": p.key, "name": p.name} for p in projects]}


@mcp.tool()
def jira_find_user_account_id(display_name: str) -> dict[str, Any]:
    client = _jira_client()
    account_id = client.find_user_account_id(display_name)
    return {"displayName": display_name, "accountId": account_id}


@mcp.tool()
def jira_create_issue(
    *,
    summary: str,
    description: str,
    issue_type: str = "Task",
    assignee_account_id: str | None = None,
    priority: str = "Medium",
    story_points: int | None = None,
    labels: list[str] | None = None,
    links: list[str] | None = None,
    quotes: list[str] | None = None,
    project_key: str | None = None,
) -> dict[str, Any]:
    client = _jira_client()
    issue = client.create_issue(
        summary=summary,
        description=description,
        issue_type=issue_type,
        assignee_account_id=assignee_account_id,
        priority=priority,
        story_points=story_points,
        labels=labels,
        links=links,
        quotes=quotes,
        project_key=project_key,
    )
    return {"key": issue.key, "url": issue.url}


@mcp.tool()
def confluence_list_spaces(limit: int = 25) -> dict[str, Any]:
    payload = _confluence_get_json("/wiki/rest/api/space", {"limit": str(limit)})
    results = payload.get("results", []) if isinstance(payload, dict) else []
    spaces = []
    for row in results:
        if not isinstance(row, dict):
            continue
        spaces.append(
            {
                "id": str(row.get("id") or ""),
                "key": str(row.get("key") or ""),
                "name": str(row.get("name") or ""),
                "type": str(row.get("type") or ""),
            }
        )
    return {"spaces": spaces}


@mcp.tool()
def confluence_search_pages(limit: int = 25, space_key: str | None = None, query: str | None = None) -> dict[str, Any]:
    cql_parts = ["type=page"]
    if space_key:
        cql_parts.append(f'space="{space_key}"')
    if query:
        safe = str(query).replace('"', '\\"')
        cql_parts.append(f'text~"{safe}"')
    cql = " AND ".join(cql_parts) + " order by lastmodified desc"
    payload = _confluence_get_json(
        "/wiki/rest/api/content/search",
        {
            "cql": cql,
            "limit": str(limit),
            "expand": "space,body.storage,version",
        },
    )
    results = payload.get("results", []) if isinstance(payload, dict) else []
    pages = []
    for row in results:
        if not isinstance(row, dict):
            continue
        body = row.get("body") if isinstance(row.get("body"), dict) else {}
        storage = body.get("storage") if isinstance(body.get("storage"), dict) else {}
        space = row.get("space") if isinstance(row.get("space"), dict) else {}
        links = row.get("_links") if isinstance(row.get("_links"), dict) else {}
        pages.append(
            {
                "id": str(row.get("id") or ""),
                "title": str(row.get("title") or ""),
                "spaceKey": str(space.get("key") or ""),
                "spaceName": str(space.get("name") or ""),
                "webui": str(links.get("webui") or ""),
                "content": str(storage.get("value") or ""),
                "version": int((row.get("version") or {}).get("number") or 0)
                if isinstance(row.get("version"), dict)
                else 0,
            }
        )
    return {"pages": pages}


if __name__ == "__main__":
    transport = (_env("MCP_SERVER_TRANSPORT", "streamable-http") or "streamable-http").lower()
    mcp.run(transport=transport)
