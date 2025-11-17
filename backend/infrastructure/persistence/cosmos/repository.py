from __future__ import annotations

import datetime
import uuid
from typing import Any, Iterable

from azure.cosmos import CosmosClient, PartitionKey, exceptions

from backend.domain.ports import MeetingsRepositoryPort
from backend.domain.status import MeetingStatus
from backend.schemas import ExtractionResult


def utc_now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class CosmosMeetingsRepository(MeetingsRepositoryPort):
    """Cosmos DB implementation of the meetings/tasks repository."""

    def __init__(
        self,
        *,
        account_uri: str,
        key: str,
        database_name: str,
        meetings_container: str,
        tasks_container: str,
        users_container: str,
        runs_container: str,
    ) -> None:
        if not account_uri or not key:
            raise ValueError("Cosmos DB account URI and key are required.")
        self._client = CosmosClient(account_uri, credential=key)
        self._db = self._create_database(database_name)
        self._meetings = self._ensure_container(
            meetings_container,
            partition_key=PartitionKey(path="/id"),
        )
        self._tasks = self._ensure_container(
            tasks_container,
            partition_key=PartitionKey(path="/meetingId"),
        )
        self._users = self._ensure_container(
            users_container,
            partition_key=PartitionKey(path="/id"),
        )
        self._runs = self._ensure_container(
            runs_container,
            partition_key=PartitionKey(path="/meetingId"),
        )

    def _create_database(self, database_name: str):
        db = self._client.get_database_client(database_name)
        try:
            db.read()
            return db
        except exceptions.CosmosResourceNotFoundError:
            self._client.create_database(id=database_name)
            return self._client.get_database_client(database_name)

    def _ensure_container(self, container_id: str, *, partition_key: PartitionKey):
        try:
            return self._db.create_container_if_not_exists(
                id=container_id,
                partition_key=partition_key,
            )
        except exceptions.CosmosResourceExistsError:
            return self._db.get_container_client(container_id)
        except exceptions.CosmosHttpResponseError as exc:  # type: ignore[attr-defined]
            sub_status = getattr(exc, "sub_status", None)
            if exc.status_code == 400 and sub_status == 1028:
                raise RuntimeError(
                    f"Cosmos container '{container_id}' already exists with an incompatible partition key. "
                    "Either delete the existing container or set COSMOS_*_CONTAINER env vars to new names."
                ) from exc
            raise

    # --- Meeting queries -------------------------------------------------

    def list_meetings(self) -> list[dict[str, Any]]:
        meetings = list(self._meetings.read_all_items())
        draft_counts: dict[str, int] = {}
        for item in meetings:
            draft_counts[item["id"]] = self._count_draft_tasks(item["id"])
        meetings.sort(key=lambda item: item.get("startedAt", item.get("createdAt", "")), reverse=True)
        return [
            self._serialize_meeting(item, draft_counts.get(item["id"], 0))
            for item in meetings
        ]

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        try:
            item = self._meetings.read_item(item=meeting_id, partition_key=meeting_id)
            return self._serialize_meeting(item, self._count_draft_tasks(meeting_id))
        except exceptions.CosmosResourceNotFoundError:
            return None

    def create_meeting(
        self,
        *,
        title: str,
        started_at: str,
        source_url: str | None,
        source_text: str | None,
    ) -> dict[str, Any]:
        meeting_id = str(uuid.uuid4())
        now = utc_now_iso()
        document = {
            "id": meeting_id,
            "title": title,
            "startedAt": started_at,
            "createdAt": now,
            "status": MeetingStatus.QUEUED.value,
            "transcript": source_text,
            "sourceUrl": source_url,
            "sourceText": source_text,
        }
        self._meetings.create_item(document)
        return self._serialize_meeting(document, 0)

    def update_meeting(self, meeting_id: str, *, title: str | None, started_at: str | None) -> dict[str, Any]:
        existing = self.get_meeting(meeting_id)
        if not existing:
            raise ValueError("Meeting not found")
        updated = existing.copy()
        if title is not None:
            updated["title"] = title
        if started_at is not None:
            updated["startedAt"] = started_at
        self._meetings.upsert_item(
            {
                "id": meeting_id,
                "title": updated["title"],
                "startedAt": updated["startedAt"],
                "createdAt": existing.get("createdAt", utc_now_iso()),
                "status": existing.get("status", MeetingStatus.QUEUED.value),
                "transcript": existing.get("transcript"),
                "sourceUrl": existing.get("sourceUrl"),
                "sourceText": existing.get("sourceText"),
            }
        )
        return self.get_meeting(meeting_id)  # refreshed with counts

    def delete_meeting(self, meeting_id: str) -> bool:
        try:
            self._meetings.delete_item(item=meeting_id, partition_key=meeting_id)
        except exceptions.CosmosResourceNotFoundError:
            return False
        self._delete_tasks_for_meeting(meeting_id)
        self._delete_runs_for_meeting(meeting_id)
        return True

    # --- Task queries ----------------------------------------------------

    def list_tasks(self, *, meeting_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        filters = []
        params: dict[str, Any] = {}
        if meeting_id:
            filters.append("c.meetingId = @meetingId")
            params["@meetingId"] = meeting_id
        if status:
            filters.append("c.status = @status")
            params["@status"] = status
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = f"SELECT * FROM c {where_clause} ORDER BY c.createdAt DESC"
        items = list(
            self._tasks.query_items(
                query=query,
                parameters=[{"name": k, "value": v} for k, v in params.items()],
                enable_cross_partition_query=not meeting_id,
            )
        )
        assignee_map = self._load_users({item.get("assigneeId") for item in items if item.get("assigneeId")})
        return [self._serialize_task(item, assignee_map) for item in items]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        query = "SELECT * FROM c WHERE c.id = @id"
        items = list(
            self._tasks.query_items(
                query=query,
                parameters=[{"name": "@id", "value": task_id}],
                enable_cross_partition_query=True,
            )
        )
        if not items:
            return None
        assignee = self._load_users({items[0].get("assigneeId")})
        return self._serialize_task(items[0], assignee)

    def update_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_task(task_id)
        if not existing:
            raise ValueError("Task not found")
        meeting_id = existing["meetingId"]
        task_doc = self._tasks.read_item(task_id, partition_key=meeting_id)
        allowed = {
            "summary": "summary",
            "description": "description",
            "issueType": "issueType",
            "priority": "priority",
            "storyPoints": "storyPoints",
            "assigneeId": "assigneeId",
            "labels": "labels",
            "status": "status",
        }
        updated = False
        for key, doc_key in allowed.items():
            if key in payload and payload[key] is not None:
                task_doc[doc_key] = payload[key]
                updated = True
        if not updated:
            return existing
        task_doc["updatedAt"] = utc_now_iso()
        self._tasks.upsert_item(task_doc)
        return self.get_task(task_id)

    def bulk_update_status(self, ids: Iterable[str], status: str) -> int:
        updated = 0
        now = utc_now_iso()
        for task in self.get_tasks_by_ids(ids):
            meeting_id = task["meetingId"]
            doc = self._tasks.read_item(task["id"], partition_key=meeting_id)
            doc["status"] = status
            doc["updatedAt"] = now
            self._tasks.upsert_item(doc)
            updated += 1
        return updated

    def get_tasks_by_ids(self, ids: Iterable[str]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        unique_ids = {task_id for task_id in ids if task_id}
        if not unique_ids:
            return []
        for task_id in unique_ids:
            task = self.get_task(task_id)
            if task:
                found.append(task)
        return found

    def mark_task_pushed_to_jira(self, task_id: str, *, issue_key: str, issue_url: str | None) -> None:
        task = self.get_task(task_id)
        if not task:
            raise ValueError("Task not found")
        doc = self._tasks.read_item(task_id, partition_key=task["meetingId"])
        doc["status"] = "approved"
        doc["jiraIssueKey"] = issue_key
        doc["jiraIssueUrl"] = issue_url
        doc["pushedToJiraAt"] = utc_now_iso()
        doc["updatedAt"] = doc["pushedToJiraAt"]
        self._tasks.upsert_item(doc)

    def list_users(self) -> list[dict[str, Any]]:
        users = list(self._users.read_all_items())
        return [
            {
                "id": user["id"],
                "displayName": user.get("displayName"),
                "email": user.get("email"),
                "jiraAccountId": user.get("jiraAccountId"),
                "voiceSamplePath": user.get("voiceSamplePath"),
            }
            for user in users
        ]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        try:
            doc = self._users.read_item(item=user_id, partition_key=user_id)
            return {
                "id": doc["id"],
                "displayName": doc.get("displayName"),
                "email": doc.get("email"),
                "jiraAccountId": doc.get("jiraAccountId"),
            }
        except exceptions.CosmosResourceNotFoundError:
            return None

    def update_user_jira_account(self, user_id: str, account_id: str) -> None:
        doc = self._users.read_item(item=user_id, partition_key=user_id)
        doc["jiraAccountId"] = account_id
        self._users.upsert_item(doc)

    # --- Ports implementation -------------------------------------------

    def create_meeting_stub(
        self,
        *,
        meeting_id: str,
        title: str,
        started_at: str,
        blob_url: str,
    ) -> None:
        now = utc_now_iso()
        document = {
            "id": meeting_id,
            "title": title,
            "startedAt": started_at,
            "createdAt": now,
            "status": MeetingStatus.QUEUED.value,
            "sourceUrl": blob_url,
        }
        self._meetings.upsert_item(document)

    def update_meeting_status(self, meeting_id: str, status: str) -> None:
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            return
        doc = self._meetings.read_item(item=meeting_id, partition_key=meeting_id)
        doc["status"] = status
        self._meetings.upsert_item(doc)

    def store_meeting_and_result(
        self,
        filename: str,
        transcript: str,
        result_model: ExtractionResult,
        *,
        meeting_id: str | None = None,
        title: str | None = None,
        started_at: str | None = None,
        blob_url: str | None = None,
    ) -> tuple[str, str]:
        meeting_id = meeting_id or str(uuid.uuid4())
        now = utc_now_iso()
        meeting_doc = {
            "id": meeting_id,
            "title": title or filename,
            "startedAt": started_at or now,
            "createdAt": now,
            "status": MeetingStatus.COMPLETED.value,
            "transcript": transcript,
            "sourceUrl": blob_url,
            "sourceText": transcript,
        }
        self._meetings.upsert_item(meeting_doc)
        self._delete_tasks_for_meeting(meeting_id)
        self._delete_runs_for_meeting(meeting_id)
        run_id = str(uuid.uuid4())
        self._runs.upsert_item(
            {
                "id": run_id,
                "meetingId": meeting_id,
                "payload": result_model.model_dump(),
                "createdAt": now,
            }
        )
        for task in result_model.tasks:
            labels = getattr(task, "labels", []) or []
            source_quote = (task.quotes or [None])[0] if getattr(task, "quotes", None) else None
            assignee_name = getattr(task, "assignee_name", None)
            assignee_id = None
            if assignee_name:
                assignee_id = self.register_voice_profile(display_name=assignee_name)
            task_doc = {
                "id": str(uuid.uuid4()),
                "meetingId": meeting_id,
                "summary": task.summary,
                "description": task.description,
                "issueType": task.issue_type.value if hasattr(task, "issue_type") else getattr(task, "issue_type", "Task"),
                "priority": task.priority.value if hasattr(task, "priority") else getattr(task, "priority", "Medium"),
                "storyPoints": getattr(task, "story_points", None),
                "assigneeId": assignee_id,
                "labels": labels,
                "status": "draft",
                "sourceQuote": source_quote,
                "createdAt": now,
                "updatedAt": now,
                "jiraIssueKey": None,
                "jiraIssueUrl": None,
            }
            self._tasks.upsert_item(task_doc)
        return meeting_id, run_id

    def register_voice_profile(self, *, display_name: str, voice_sample_path: str | None = None) -> str:
        normalized = display_name.strip()
        if not normalized:
            raise ValueError("display_name is required")
        query = "SELECT * FROM c WHERE LOWER(c.displayName) = @name"
        params = [{"name": "@name", "value": normalized.lower()}]
        existing = list(
            self._users.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
        if existing:
            doc = existing[0]
            if voice_sample_path:
                doc["voiceSamplePath"] = voice_sample_path
                self._users.upsert_item(doc)
            return doc["id"]
        user_id = str(uuid.uuid4())
        self._users.upsert_item(
            {
                "id": user_id,
                "displayName": normalized,
                "voiceSamplePath": voice_sample_path,
            }
        )
        return user_id

    def update_user_voice_sample(self, user_id: str, display_name: str, voice_sample_path: str) -> str:
        normalized = display_name.strip()
        if not normalized:
            raise ValueError("display_name is required")
        try:
            doc = self._users.read_item(item=user_id, partition_key=user_id)
        except exceptions.CosmosResourceNotFoundError:
            raise ValueError("User not found") from None
        doc["displayName"] = normalized
        doc["voiceSamplePath"] = voice_sample_path
        self._users.upsert_item(doc)
        return user_id

    # --- Helpers ---------------------------------------------------------

    def _serialize_meeting(self, item: dict[str, Any], draft_count: int) -> dict[str, Any]:
        started = item.get("startedAt") or item.get("createdAt") or utc_now_iso()
        return {
            "id": item["id"],
            "title": item.get("title"),
            "startedAt": started,
            "status": item.get("status", MeetingStatus.QUEUED.value),
            "draftTaskCount": draft_count,
            "transcript": item.get("transcript"),
        }

    def _serialize_task(self, item: dict[str, Any], users: dict[str, dict[str, Any]]) -> dict[str, Any]:
        assignee_id = item.get("assigneeId")
        assignee = users.get(assignee_id) if assignee_id else None
        return {
            "id": item["id"],
            "meetingId": item.get("meetingId"),
            "summary": item.get("summary"),
            "description": item.get("description") or "",
            "issueType": item.get("issueType"),
            "priority": item.get("priority"),
            "storyPoints": item.get("storyPoints"),
            "assigneeId": assignee_id,
            "assigneeAccountId": assignee.get("jiraAccountId") if assignee else None,
            "labels": item.get("labels") or [],
            "status": item.get("status"),
            "sourceQuote": item.get("sourceQuote"),
            "jiraIssueKey": item.get("jiraIssueKey"),
            "jiraIssueUrl": item.get("jiraIssueUrl"),
            "pushedToJiraAt": item.get("pushedToJiraAt"),
        }

    def _load_users(self, user_ids: set[str | None]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for user_id in user_ids:
            if not user_id:
                continue
            try:
                doc = self._users.read_item(item=user_id, partition_key=user_id)
                result[user_id] = doc
            except exceptions.CosmosResourceNotFoundError:
                continue
        return result

    def _delete_tasks_for_meeting(self, meeting_id: str) -> None:
        query = "SELECT c.id FROM c WHERE c.meetingId = @meetingId"
        params = [{"name": "@meetingId", "value": meeting_id}]
        items = list(
            self._tasks.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=False,
            )
        )
        for item in items:
            self._tasks.delete_item(item=item["id"], partition_key=meeting_id)

    def _delete_runs_for_meeting(self, meeting_id: str) -> None:
        query = "SELECT c.id FROM c WHERE c.meetingId = @meetingId"
        params = [{"name": "@meetingId", "value": meeting_id}]
        items = list(
            self._runs.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=False,
            )
        )
        for item in items:
            self._runs.delete_item(item=item["id"], partition_key=meeting_id)

    def _count_draft_tasks(self, meeting_id: str) -> int:
        query = "SELECT VALUE COUNT(1) FROM c WHERE c.meetingId = @meetingId AND c.status = 'draft'"
        params = [{"name": "@meetingId", "value": meeting_id}]
        result = list(
            self._tasks.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=False,
            )
        )
        if not result:
            return 0
        return int(result[0])
