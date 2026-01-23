"""
Bulk-create mock issues in Jira for RAG estimation testing.

Usage:
  export JIRA_BASE_URL="https://your-domain.atlassian.net"
  export JIRA_EMAIL="you@example.com"
  export JIRA_API_TOKEN="your_api_token"
  export JIRA_PROJECT_KEY="SCRUM"
  # Optional: override if your Story Points field uses a different id
  export JIRA_STORY_POINTS_FIELD="customfield_10016"
  python scripts/jira_bulk_upload.py

Notes:
- Do not commit tokens. Run locally.
- If Story Points fail to set, check your Jira field id under Project Settings → Issues → Custom fields.
"""

import json
import os
import sys
from typing import List

from dotenv import load_dotenv
load_dotenv()
import requests


JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY")
STORY_POINTS_FIELD = os.environ.get("JIRA_STORY_POINTS_FIELD", "customfield_10016")
ASSIGNEE_MAP = {
    "Waldemar Walasik": os.environ.get("JIRA_ASSIGNEE_WALDEMAR"),
    "Adrian Puchacki": os.environ.get("JIRA_ASSIGNEE_ADRIAN"),
    "Wojciech Puczyk": os.environ.get("JIRA_ASSIGNEE_WOJCIECH"),
}


ISSUES = [
    {
        "summary": "Parallelize preprocessing with Dask",
        "description": "Fan-out preprocessing across workers; add retries and metrics dashboard; ensure idempotent writes.",
        "acceptance": [
            "Parallel fan-out can be toggled on/off",
            "Metrics dashboard shows worker throughput and lag",
            "Retries with backoff on worker failure",
        ],
        "points": 5,
        "labels": ["component:preprocessing", "type:feature", "risk:med"],
        "issuetype": "Story",
        "assignee": "Wojciech Puczyk",
    },
    {
        "summary": "Update model registry and redeploy via MLflow",
        "description": "Register new model version, transition stage, and smoke test serving endpoint.",
        "acceptance": [
            "Model version registered and staged",
            "Smoke test passes on serving endpoint",
            "Rollback path documented",
        ],
        "points": 3,
        "labels": ["component:registry", "type:feature", "risk:low"],
        "issuetype": "Story",
        "assignee": "Waldemar Walasik",
    },
    {
        "summary": "Add drift detection rule (>3% accuracy drop) with Slack alert",
        "description": "Configure drift rule, send Slack notification, and log to MLflow.",
        "acceptance": [
            "Rule configured against baseline",
            "Alert fires on simulated >3% drop",
            "MLflow log updated with drift metrics",
        ],
        "points": 3,
        "labels": ["component:monitoring", "type:feature", "risk:med"],
        "issuetype": "Story",
        "assignee": "Waldemar Walasik",
    },
    {
        "summary": "Release-readiness brief and checklist",
        "description": "Publish release brief with stakeholder links and complete checklist.",
        "acceptance": [
            "Brief published to docs",
            "Checklist completed",
            "Stakeholder links are current",
        ],
        "points": 1,
        "labels": ["component:docs", "type:chore", "risk:low"],
        "issuetype": "Story",
        "assignee": "Adrian Puchacki",
    },
    {
        "summary": "Fix SAS CORS for uploads",
        "description": "Allow PUT/OPTIONS from localhost; verify upload flow succeeds.",
        "acceptance": [
            "CORS allows PUT and OPTIONS from localhost",
            "Regression upload test passes",
        ],
        "points": 2,
        "labels": ["component:blob", "type:bug", "risk:med"],
        "issuetype": "Bug",
        "assignee": "Waldemar Walasik",
    },
    {
        "summary": "Add canary deploy toggle for serving endpoint",
        "description": "Add feature flag for canary; test rollback; monitor latency.",
        "acceptance": [
            "Toggle present and documented",
            "Rollback path tested",
            "Latency monitored during canary",
        ],
        "points": 3,
        "labels": ["component:serving", "type:infra", "risk:med"],
        "issuetype": "Story",
        "assignee": "Waldemar Walasik",
    },
    {
        "summary": "Backfill embeddings for new Confluence pages",
        "description": "Ingest new pages, build index with metadata, and spot-check relevance.",
        "acceptance": [
            "Pages ingested with metadata",
            "Index built and healthy",
            "Relevance spot-check passes",
        ],
        "points": 3,
        "labels": ["component:rag", "type:data", "risk:low"],
        "issuetype": "Story",
        "assignee": "Adrian Puchacki",
    },
    {
        "summary": "Tune drift threshold per segment",
        "description": "Set per-segment thresholds to reduce alert noise; log metrics.",
        "acceptance": [
            "Segment thresholds set",
            "Alert noise reduced in tests",
            "Metrics logged to MLflow",
        ],
        "points": 5,
        "labels": ["component:monitoring", "type:ml", "risk:med"],
        "issuetype": "Story",
        "assignee": "Waldemar Walasik",
    },
    {
        "summary": "Ambiguous performance task (should refuse in RAG)",
        "description": "Improve performance without specified component or target.",
        "acceptance": [],
        "points": None,
        "labels": ["component:unknown", "type:feature", "risk:high"],
        "issuetype": "Story",
        "assignee": "Adrian Puchacki",
    },
    {
        "summary": "Edge: massive data migration with unclear rollback",
        "description": "Migrate 10TB of telemetry to new schema; no rollback defined.",
        "acceptance": [],
        "points": 8,
        "labels": ["component:data", "type:migration", "risk:high"],
        "issuetype": "Story",
        "assignee": "Waldemar Walasik",
    },
    {
        "summary": "Outlier: latency target 10ms for transcript search",
        "description": "Make search super fast like Google but we don't want to change infra.",
        "acceptance": [
            "p95 latency <= 10ms for transcript queries (stretch)",
            "No infra changes (contradiction to discuss)",
        ],
        "points": None,
        "labels": ["component:search", "type:feature", "risk:high"],
        "issuetype": "Story",
        "assignee": "Wojciech Puczyk",
    },
    {
        "summary": "Hard: cross-tenant isolation audit",
        "description": "Prove embeddings and indices are tenant-isolated; produce audit doc.",
        "acceptance": [
            "Checklist of isolation controls",
            "Red-team test results attached",
            "Audit doc approved by security",
        ],
        "points": 5,
        "labels": ["component:security", "type:audit", "risk:high"],
        "issuetype": "Story",
        "assignee": "Adrian Puchacki",
    },
    {
        "summary": "Noisy: 'do the thing with the stuff'",
        "description": "do the thing with the stuff before launch",
        "acceptance": [],
        "points": None,
        "labels": ["component:unknown", "type:feature", "risk:high"],
        "issuetype": "Story",
        "assignee": "Wojciech Puczyk",
    },
    {
        "summary": "Long AC edge case",
        "description": "Extend ingestion pipeline with fallback blob region.",
        "acceptance": [
            "Fallback region configured",
            "Failover test simulated",
            "SAS token generation updated for multi-region",
            "Docs updated",
            "Runbook includes traffic cutover steps",
            "Alerting added for region failover",
        ],
        "points": 5,
        "labels": ["component:blob", "type:infra", "risk:med"],
        "issuetype": "Story",
        "assignee": "Waldemar Walasik",
    },
    {
        "summary": "Refusal case: missing acceptance criteria",
        "description": "Build something cool for stakeholders ASAP.",
        "acceptance": [],
        "points": None,
        "labels": ["component:unknown", "type:feature", "risk:high"],
        "issuetype": "Story",
        "assignee": "Adrian Puchacki",
    },
    {
        "summary": "Data quality monitors for transcripts",
        "description": "Add freshness and completeness checks on transcript ingestion.",
        "acceptance": [
            "Freshness alert if >1 hour delay",
            "Completeness check on chunk counts",
            "Dashboard panel for data quality",
        ],
        "points": 3,
        "labels": ["component:data", "type:monitoring", "risk:med"],
        "issuetype": "Story",
        "assignee": "Wojciech Puczyk",
    },
    {
        "summary": "GPU cost reduction experiment",
        "description": "Cut inference cost by 20% without latency regression.",
        "acceptance": [
            "Cost per 1k requests reduced by 20%",
            "p95 latency unchanged (+/-5%)",
            "Experiment results logged",
        ],
        "points": 5,
        "labels": ["component:serving", "type:experiment", "risk:med"],
        "issuetype": "Story",
        "assignee": "Waldemar Walasik",
    },
    {
        "summary": "Compliance: add PII scrubbing to transcripts",
        "description": "Scrub PII before indexing; document controls.",
        "acceptance": [
            "PII patterns redacted",
            "Unit + integration tests for scrubbing",
            "Docs updated for compliance",
        ],
        "points": 3,
        "labels": ["component:ingestion", "type:compliance", "risk:high"],
        "issuetype": "Story",
        "assignee": "Adrian Puchacki",
    },
]

# Summaries already uploaded; skip to avoid duplicates.
SKIP_SUMMARIES = {
    "Parallelize preprocessing with Dask",
    "Update model registry and redeploy via MLflow",
    "Add drift detection rule (>3% accuracy drop) with Slack alert",
    "Release-readiness brief and checklist",
    "Fix SAS CORS for uploads",
    "Add canary deploy toggle for serving endpoint",
    "Backfill embeddings for new Confluence pages",
    "Tune drift threshold per segment",
    "Ambiguous performance task (should refuse in RAG)",
}


def validate_env():
    missing = [k for k, v in [
        ("JIRA_BASE_URL", JIRA_BASE_URL),
        ("JIRA_EMAIL", JIRA_EMAIL),
        ("JIRA_API_TOKEN", JIRA_API_TOKEN),
        ("JIRA_PROJECT_KEY", JIRA_PROJECT_KEY),
    ] if not v]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}")


def build_payload(issue: dict) -> dict:
    def make_adf(desc: str, acceptance: list) -> dict:
        content = []
        if desc:
            content.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": desc}],
            })
        if acceptance:
            content.append({"type": "paragraph", "content": [{"type": "text", "text": "Acceptance Criteria:"}]})
            bullets = []
            for ac in acceptance:
                bullets.append({
                    "type": "listItem",
                    "content": [{
                        "type": "paragraph",
                        "content": [{"type": "text", "text": ac}],
                    }],
                })
            content.append({"type": "bulletList", "content": bullets})
        return {"type": "doc", "version": 1, "content": content}

    description_adf = make_adf(issue["description"], issue.get("acceptance", []))
    fields = {
        "project": {"key": JIRA_PROJECT_KEY},
        "summary": issue["summary"],
        "description": description_adf,
        "issuetype": {"name": issue.get("issuetype", "Story")},
        "labels": issue.get("labels", []),
    }
    if STORY_POINTS_FIELD and issue.get("points") is not None:
        fields[STORY_POINTS_FIELD] = issue["points"]
    assignee_name = issue.get("assignee")
    account_id = ASSIGNEE_MAP.get(assignee_name) if assignee_name else None
    if account_id:
        fields["assignee"] = {"id": account_id}
    return {"fields": fields}


def create_issue(issue: dict) -> str:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    payload = build_payload(issue)
    resp = requests.post(url, headers=headers, auth=auth, data=json.dumps(payload))
    if resp.status_code >= 300:
        raise RuntimeError(f"Failed to create {issue['summary']}: {resp.status_code} {resp.text}")
    return resp.json().get("key", "")


def main():
    validate_env()
    created: List[str] = []
    for issue in ISSUES:
        if issue["summary"] in SKIP_SUMMARIES:
            print(f"Skipping (already uploaded): {issue['summary']}")
            continue
        key = create_issue(issue)
        created.append(key)
        print(f"Created {key}: {issue['summary']}")
    print("Done. Created issues:", ", ".join(created))


if __name__ == "__main__":
    main()
