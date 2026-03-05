from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from backend.infrastructure.mcp import MCPAtlassianClient
from backend.schemas import ExtractionResult, Task

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional at runtime
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover
    LANGGRAPH_AVAILABLE = False
    StateGraph = None  # type: ignore[assignment]
    START = "START"  # type: ignore[assignment]
    END = "END"  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency path
    from langchain_openai import AzureOpenAIEmbeddings, OpenAIEmbeddings
except Exception:  # pragma: no cover
    AzureOpenAIEmbeddings = None  # type: ignore[assignment]
    OpenAIEmbeddings = None  # type: ignore[assignment]


@dataclass
class RetrievedContext:
    score: float
    text: str
    metadata: dict[str, Any]


@dataclass
class KnowledgeDoc:
    text: str
    metadata: dict[str, Any]
    vector: list[float]


@dataclass
class RAGConfig:
    """Configuration for LangChain/LangGraph RAG enrichment."""

    # Backward-compatible fields kept for existing env/test contracts.
    persist_dir: Path = Path(os.getenv("RAG_INDEX_DIR", "data/rag_index"))
    qdrant_url: str | None = os.getenv("QDRANT_URL")
    qdrant_api_key: str | None = os.getenv("QDRANT_API_KEY")
    qdrant_grpc: bool = os.getenv("QDRANT_GRPC", "0").lower() in {"1", "true", "yes", "on"}
    qdrant_location: str | None = os.getenv("QDRANT_LOCATION", "data/rag_qdrant")
    collection: str = os.getenv("RAG_COLLECTION", "sprint-planning")
    confluence_dir: Path = Path(os.getenv("RAG_CONFLUENCE_DIR", "mock_confluence"))
    top_k: int = int(os.getenv("RAG_TOP_K", "8"))
    rerank_top_k: int = int(os.getenv("RAG_RERANK_TOP_K", "4"))
    embedding_model: str = os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-3-small")
    description_model: str = os.getenv("RAG_LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    max_context_chars: int = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "2000"))
    confluence_live_enabled: bool = os.getenv("RAG_CONFLUENCE_LIVE_ENABLED", "1").lower() in {"1", "true", "yes", "on"}
    confluence_live_pages_limit: int = int(os.getenv("RAG_CONFLUENCE_LIVE_PAGES_LIMIT", "20"))
    confluence_live_spaces_limit: int = int(os.getenv("RAG_CONFLUENCE_LIVE_SPACES_LIMIT", "5"))
    confluence_mock_enabled: bool = os.getenv("RAG_CONFLUENCE_MOCK_ENABLED", "1").lower() in {"1", "true", "yes", "on"}
    confluence_mock_space_key: str = os.getenv("RAG_CONFLUENCE_MOCK_SPACE_KEY", "ENG")
    confluence_live_space_keys: list[str] = field(
        default_factory=lambda: [x.strip() for x in (os.getenv("RAG_CONFLUENCE_SPACE_KEYS") or "").split(",") if x.strip()]
    )
    use_mock_embeddings: bool = field(
        default_factory=lambda: os.getenv("MOCK_RAG", "0").lower() in {"1", "true", "yes", "on"}
    )


class RAGPipelineState(TypedDict, total=False):
    transcript: str
    meeting_id: str | None
    project_key: str | None
    confluence_access_token: str | None
    tasks: list[Task]
    history_rows: list[Mapping[str, Any]]
    old_task_docs: list[tuple[str, dict[str, Any]]]
    confluence_docs: list[tuple[str, dict[str, Any]]]
    transcript_docs: list[tuple[str, dict[str, Any]]]
    knowledge_docs: list[KnowledgeDoc]
    contexts_by_task: dict[int, list[RetrievedContext]]
    fallback_average_points: int | None


class RAGEstimator:
    """LangChain + LangGraph task enrichment for points and better descriptions."""

    def __init__(self, config: RAGConfig | None = None) -> None:
        self._config = config or RAGConfig()
        self._embedder = self._build_embedder()
        self._description_llm = self._build_description_llm()
        self._mcp_client = self._build_mcp_client()
        self._pipeline_graph = self._build_pipeline_graph()

    def _build_embedder(self):
        if self._config.use_mock_embeddings:
            return None

        provider = os.getenv("LLM_PROVIDER", "azure").lower()
        api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        try:
            if provider == "azure" and AzureOpenAIEmbeddings:
                deployment = os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT")
                endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
                if deployment and endpoint:
                    return AzureOpenAIEmbeddings(
                        azure_deployment=deployment,
                        azure_endpoint=endpoint,
                        api_key=api_key,
                        openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                    )
            if OpenAIEmbeddings:
                return OpenAIEmbeddings(model=self._config.embedding_model, api_key=api_key)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Falling back to deterministic embeddings: %s", exc)
        return None

    def _build_description_llm(self):
        provider = os.getenv("LLM_PROVIDER", "azure").lower()
        api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        try:
            if provider == "azure":
                deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
                endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
                if deployment and endpoint:
                    return AzureChatOpenAI(
                        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                        azure_deployment=deployment,
                        azure_endpoint=endpoint,
                        temperature=0.1,
                    )
            return ChatOpenAI(model=self._config.description_model, api_key=api_key, temperature=0.1)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Description enhancer disabled: %s", exc)
            return None

    def _build_mcp_client(self) -> MCPAtlassianClient | None:
        if not self._config.confluence_live_enabled:
            return None
        if os.getenv("MCP_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
            return None
        url = (os.getenv("MCP_CONFLUENCE_SERVER_URL") or os.getenv("MCP_ATLASSIAN_SERVER_URL") or "").strip()
        if not url:
            return None
        try:
            return MCPAtlassianClient(server_url=url, timeout_seconds=float(os.getenv("MCP_TIMEOUT_SECONDS", "20")))
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Failed to initialize MCP Confluence client: %s", exc)
            return None

    def _build_pipeline_graph(self):
        if not LANGGRAPH_AVAILABLE or StateGraph is None:
            return None
        graph = StateGraph(RAGPipelineState)
        graph.add_node("collect_old_tasks", self._node_collect_old_tasks)
        graph.add_node("collect_confluence_data", self._node_collect_confluence_data)
        graph.add_node("collect_transcript_data", self._node_collect_transcript_data)
        graph.add_node("build_knowledge_base", self._node_build_knowledge_base)
        graph.add_node("estimate_points", self._node_estimate_points)
        graph.add_node("improve_description", self._node_improve_description)
        graph.add_edge(START, "collect_old_tasks")
        graph.add_edge("collect_old_tasks", "collect_confluence_data")
        graph.add_edge("collect_confluence_data", "collect_transcript_data")
        graph.add_edge("collect_transcript_data", "build_knowledge_base")
        graph.add_edge("build_knowledge_base", "estimate_points")
        graph.add_edge("estimate_points", "improve_description")
        graph.add_edge("improve_description", END)
        return graph.compile()

    def _embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._embedder:
            try:
                return [list(vec) for vec in self._embedder.embed_documents(list(texts))]
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.warning("Embedding provider failed; using deterministic vectors: %s", exc)
        return [self._deterministic_vector(text) for text in texts]

    @staticmethod
    def _deterministic_vector(text: str, dims: int = 64) -> list[float]:
        vector = [0.0] * dims
        for token in (text or "").lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = digest[0] % dims
            vector[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector

    @staticmethod
    def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
        if not a or not b:
            return 0.0
        size = min(len(a), len(b))
        dot = sum(a[i] * b[i] for i in range(size))
        a_norm = math.sqrt(sum(x * x for x in a[:size]))
        b_norm = math.sqrt(sum(x * x for x in b[:size]))
        if a_norm == 0 or b_norm == 0:
            return 0.0
        return dot / (a_norm * b_norm)

    def _seed_confluence_docs(self) -> list[tuple[str, dict[str, Any]]]:
        docs: list[tuple[str, dict[str, Any]]] = []
        if not self._config.confluence_dir.exists():
            return docs
        for path in sorted(self._config.confluence_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue
            docs.append(
                (
                    text,
                    {
                        "source": "confluence",
                        "source_id": path.name,
                        "title": path.stem,
                        "story_points": None,
                    },
                )
            )
        return docs

    @staticmethod
    def _strip_html(value: str) -> str:
        return re.sub(r"<[^>]+>", " ", value or "").replace("&nbsp;", " ").strip()

    def _oauth_accessible_resources(self, access_token: str) -> list[dict[str, Any]]:
        req = urllib.request.Request(
            "https://api.atlassian.com/oauth/token/accessible-resources",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "[]")
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
            return []
        return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []

    def _confluence_search_pages_via_site(
        self,
        *,
        site_url: str,
        access_token: str,
        limit: int,
        space_key: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        cql_parts = ["type=page"]
        if space_key:
            cql_parts.append(f'space="{space_key}"')
        if query:
            safe = str(query).replace('"', '\\"')
            cql_parts.append(f'text~"{safe}"')
        cql = " AND ".join(cql_parts) + " order by lastmodified desc"
        q = urllib.parse.urlencode({"cql": cql, "limit": str(limit), "expand": "space,body.storage,version,_links"})
        url = f"{site_url.rstrip('/')}/wiki/rest/api/content/search?{q}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
            return []
        results = payload.get("results", []) if isinstance(payload, dict) else []
        pages: list[dict[str, Any]] = []
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
                    "spaceKey": str(space.get("key") or space_key or ""),
                    "spaceName": str(space.get("name") or ""),
                    "webui": str(links.get("webui") or ""),
                    "content": self._strip_html(str(storage.get("value") or "")),
                }
            )
        return pages

    def _collect_confluence_docs_live(self, access_token: str | None) -> list[tuple[str, dict[str, Any]]]:
        if not self._mcp_client:
            return self._collect_confluence_docs_live_oauth(access_token)
        docs = self._collect_confluence_docs_live_oauth(access_token)
        if docs:
            return docs
        return self._collect_confluence_docs_live_mcp()

    def _collect_confluence_docs_live_oauth(self, access_token: str | None) -> list[tuple[str, dict[str, Any]]]:
        token = (access_token or "").strip()
        if not token:
            return []
        docs: list[tuple[str, dict[str, Any]]] = []
        pages_limit = max(1, self._config.confluence_live_pages_limit)
        resources = self._oauth_accessible_resources(token)
        if not resources:
            return []

        space_filter = {x.upper() for x in self._config.confluence_live_space_keys}
        for resource in resources:
            scopes = [str(x) for x in (resource.get("scopes") or []) if isinstance(x, str)]
            if not any(scope.startswith("read:confluence") for scope in scopes):
                continue
            site_url = str(resource.get("url") or "").strip()
            if not site_url:
                continue
            if space_filter:
                for space_key in sorted(space_filter):
                    pages = self._confluence_search_pages_via_site(
                        site_url=site_url,
                        access_token=token,
                        limit=pages_limit,
                        space_key=space_key,
                    )
                    for row in pages:
                        content = str(row.get("content") or "").strip()
                        title = str(row.get("title") or "").strip()
                        if not content:
                            continue
                        docs.append(
                            (
                                f"{title}\n\n{content}".strip(),
                                {
                                    "source": "confluence_live",
                                    "source_id": str(row.get("id") or ""),
                                    "title": title,
                                    "space_key": str(row.get("spaceKey") or space_key),
                                    "story_points": None,
                                    "webui": str(row.get("webui") or ""),
                                },
                            )
                        )
            else:
                pages = self._confluence_search_pages_via_site(
                    site_url=site_url,
                    access_token=token,
                    limit=pages_limit,
                )
                for row in pages:
                    content = str(row.get("content") or "").strip()
                    title = str(row.get("title") or "").strip()
                    if not content:
                        continue
                    docs.append(
                        (
                            f"{title}\n\n{content}".strip(),
                            {
                                "source": "confluence_live",
                                "source_id": str(row.get("id") or ""),
                                "title": title,
                                "space_key": str(row.get("spaceKey") or ""),
                                "story_points": None,
                                "webui": str(row.get("webui") or ""),
                            },
                        )
                    )
        return docs

    def _collect_confluence_docs_live_mcp(self) -> list[tuple[str, dict[str, Any]]]:
        if not self._mcp_client:
            return []
        docs: list[tuple[str, dict[str, Any]]] = []
        pages_limit = max(1, self._config.confluence_live_pages_limit)
        try:
            space_keys = list(self._config.confluence_live_space_keys)
            if not space_keys:
                spaces = self._mcp_client.list_confluence_spaces(limit=max(1, self._config.confluence_live_spaces_limit))
                space_keys = [str(row.get("key") or "").strip() for row in spaces if isinstance(row, dict)]
                space_keys = [key for key in space_keys if key]
            if not space_keys:
                pages = self._mcp_client.search_confluence_pages(limit=pages_limit)
                for row in pages:
                    content = str(row.get("content") or "").strip()
                    title = str(row.get("title") or "").strip()
                    if not content:
                        continue
                    docs.append(
                        (
                            f"{title}\n\n{content}".strip(),
                            {
                                "source": "confluence_live",
                                "source_id": str(row.get("id") or ""),
                                "title": title,
                                "space_key": str(row.get("spaceKey") or ""),
                                "story_points": None,
                                "webui": str(row.get("webui") or ""),
                            },
                        )
                    )
                return docs

            for key in space_keys:
                pages = self._mcp_client.search_confluence_pages(limit=pages_limit, space_key=key)
                for row in pages:
                    content = str(row.get("content") or "").strip()
                    title = str(row.get("title") or "").strip()
                    if not content:
                        continue
                    docs.append(
                        (
                            f"{title}\n\n{content}".strip(),
                            {
                                "source": "confluence_live",
                                "source_id": str(row.get("id") or ""),
                                "title": title,
                                "space_key": str(row.get("spaceKey") or key),
                                "story_points": None,
                                "webui": str(row.get("webui") or ""),
                            },
                        )
                    )
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Live Confluence retrieval failed: %s", exc)
        return docs

    @staticmethod
    def _task_to_text(task: Mapping[str, Any]) -> str:
        return f"{(task.get('summary') or '').strip()}\n\n{(task.get('description') or '').strip()}".strip()

    @staticmethod
    def _split_transcript(transcript: str, *, chunk_chars: int = 700, overlap: int = 120) -> list[str]:
        text = (transcript or "").strip()
        if not text:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + chunk_chars)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(0, end - overlap)
        return chunks

    @staticmethod
    def _task_query(task: Task) -> str:
        labels = " ".join(task.labels or [])
        return f"{task.summary}\n{task.description}\nLabels: {labels}".strip()

    def _retrieve_contexts(self, task: Task, docs: list[KnowledgeDoc]) -> list[RetrievedContext]:
        if not docs:
            return []
        query_vector = self._embed_texts([self._task_query(task)])[0]
        ranked: list[RetrievedContext] = []
        for doc in docs:
            score = self._cosine_similarity(query_vector, doc.vector)
            ranked.append(RetrievedContext(score=score, text=doc.text, metadata=dict(doc.metadata)))
        ranked.sort(key=lambda item: item.score, reverse=True)
        top_k = max(1, self._config.top_k)
        rerank_k = max(1, self._config.rerank_top_k)
        return ranked[:top_k][:rerank_k]

    @staticmethod
    def _estimate_points(contexts: list[RetrievedContext]) -> int | None:
        values: list[int] = []
        for ctx in contexts:
            points = ctx.metadata.get("story_points")
            if points is None:
                continue
            try:
                values.append(int(points))
            except (TypeError, ValueError):
                continue
        if not values:
            return None
        return round(sum(values) / len(values))

    @staticmethod
    def _average_history_points(history_tasks: Iterable[Mapping[str, Any]]) -> int | None:
        values: list[int] = []
        for row in history_tasks:
            points = row.get("storyPoints")
            if points is None:
                continue
            try:
                values.append(int(points))
            except (TypeError, ValueError):
                continue
        if not values:
            return None
        return round(sum(values) / len(values))

    def _llm_improve_description(self, task: Task, contexts: list[RetrievedContext]) -> str:
        if not self._description_llm:
            return self._heuristic_improve_description(task, contexts)

        context_lines: list[str] = []
        for ctx in contexts[:3]:
            snippet = " ".join(ctx.text.split())[:220]
            source = ctx.metadata.get("source", "unknown")
            context_lines.append(f"[{source}] {snippet}")
        context_blob = "\n".join(context_lines)[: self._config.max_context_chars]
        current = (task.description or "").strip()

        prompt = (
            "Improve task description for Jira. Keep it concrete and actionable.\n"
            "Return plain text only (no JSON, no markdown heading).\n"
            "Mention scope, acceptance criteria and dependencies when evident from context.\n"
            f"Task summary: {task.summary}\n"
            f"Current description: {current}\n"
            f"Context:\n{context_blob}"
        )
        try:
            response = self._description_llm.invoke(
                [
                    SystemMessage(content="You are a senior engineering manager writing high-quality Jira task descriptions."),
                    HumanMessage(content=prompt),
                ]
            )
            text = (response.content or "").strip() if hasattr(response, "content") else ""
            if isinstance(text, list):
                parts = []
                for item in text:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, Mapping) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                text = "".join(parts).strip()
            return text or self._heuristic_improve_description(task, contexts)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Description LLM improvement failed, using heuristic: %s", exc)
            return self._heuristic_improve_description(task, contexts)

    @staticmethod
    def _heuristic_improve_description(task: Task, contexts: list[RetrievedContext]) -> str:
        base = (task.description or "").strip()
        if not base:
            base = f"Implement: {task.summary.strip()}."
        lines = [base]
        snippets: list[str] = []
        for ctx in contexts[:2]:
            snippet = " ".join(ctx.text.split())
            if not snippet:
                continue
            snippets.append(snippet[:140])
        if snippets:
            lines.append("Context references:")
            for snippet in snippets:
                lines.append(f"- {snippet}")
        return "\n".join(lines).strip()

    def _node_collect_old_tasks(self, state: RAGPipelineState) -> dict[str, Any]:
        history_rows = list(state.get("history_rows") or [])
        docs: list[tuple[str, dict[str, Any]]] = []
        for row in history_rows:
            text = self._task_to_text(row)
            if not text:
                continue
            task_id = row.get("id") or hashlib.sha256(text.encode("utf-8")).hexdigest()
            docs.append(
                (
                    text,
                    {
                        "source": "history",
                        "source_id": task_id,
                        "title": (row.get("summary") or "")[:120],
                        "story_points": row.get("storyPoints"),
                    },
                )
            )
        return {"old_task_docs": docs, "fallback_average_points": self._average_history_points(history_rows)}

    def _build_mock_confluence_docs(self, state: RAGPipelineState) -> list[tuple[str, dict[str, Any]]]:
        if not self._config.confluence_mock_enabled:
            return []
        tasks = list(state.get("tasks") or [])
        if not tasks:
            return []
        project_key = (state.get("project_key") or "SPR").strip() or "SPR"
        space_key = (self._config.confluence_mock_space_key or "ENG").strip() or "ENG"
        meeting_id = (state.get("meeting_id") or "draft").strip() or "draft"
        transcript = str(state.get("transcript") or "")
        transcript_excerpt = " ".join(transcript.split())[:450]

        docs: list[tuple[str, dict[str, Any]]] = []
        for idx, task in enumerate(tasks[:3], start=1):
            title = f"{project_key} Delivery Notes - {task.summary[:64]}"
            page_id = f"mock-{project_key.lower()}-{meeting_id[:8]}-{idx}"
            webui = f"/wiki/spaces/{space_key}/pages/{100000+idx}/{urllib.parse.quote(title)}"
            body = (
                f"Page title: {title}\n"
                f"Space: {space_key}\n"
                f"Status: Approved for sprint execution\n\n"
                f"Background:\n{task.description.strip()}\n\n"
                f"Implementation guidance:\n"
                f"- Align scope with sprint goal and stakeholder expectations.\n"
                f"- Keep acceptance criteria measurable and demo-ready.\n"
                f"- Capture risks and dependencies in Jira task description.\n\n"
                f"Acceptance criteria template:\n"
                f"1. Functional outcome is implemented and validated.\n"
                f"2. Regression impact is assessed.\n"
                f"3. Rollout and fallback are documented.\n\n"
                f"Meeting excerpt:\n{transcript_excerpt}"
            ).strip()
            docs.append(
                (
                    f"{title}\n\n{body}",
                    {
                        "source": "confluence_live",
                        "source_id": page_id,
                        "title": title,
                        "space_key": space_key,
                        "story_points": None,
                        "webui": webui,
                        "mocked": True,
                    },
                )
            )
        return docs

    def _node_collect_confluence_data(self, state: RAGPipelineState) -> dict[str, Any]:
        live_docs = self._collect_confluence_docs_live(state.get("confluence_access_token"))
        if live_docs:
            return {"confluence_docs": live_docs}
        seeded_docs = self._seed_confluence_docs()
        if seeded_docs:
            return {"confluence_docs": seeded_docs}
        return {"confluence_docs": self._build_mock_confluence_docs(state)}

    def _node_collect_transcript_data(self, state: RAGPipelineState) -> dict[str, Any]:
        transcript = str(state.get("transcript") or "")
        meeting_id = state.get("meeting_id")
        project_key = state.get("project_key")
        chunks = self._split_transcript(transcript)
        docs: list[tuple[str, dict[str, Any]]] = []
        for idx, chunk in enumerate(chunks):
            docs.append(
                (
                    chunk,
                    {
                        "source": "transcript",
                        "source_id": f"{meeting_id or 'unknown'}:{idx}",
                        "project_key": project_key,
                        "story_points": None,
                    },
                )
            )
        return {"transcript_docs": docs}

    def _node_build_knowledge_base(self, state: RAGPipelineState) -> dict[str, Any]:
        raw_docs = list(state.get("old_task_docs") or [])
        raw_docs.extend(state.get("confluence_docs") or [])
        raw_docs.extend(state.get("transcript_docs") or [])
        vectors = self._embed_texts([text for text, _ in raw_docs])
        knowledge_docs = [KnowledgeDoc(text=text, metadata=meta, vector=vec) for (text, meta), vec in zip(raw_docs, vectors)]
        return {"knowledge_docs": knowledge_docs}

    def _node_estimate_points(self, state: RAGPipelineState) -> dict[str, Any]:
        tasks = list(state.get("tasks") or [])
        docs = list(state.get("knowledge_docs") or [])
        fallback = state.get("fallback_average_points")
        contexts_by_task: dict[int, list[RetrievedContext]] = {}

        for idx, task in enumerate(tasks):
            contexts = self._retrieve_contexts(task, docs)
            contexts_by_task[idx] = contexts
            if task.story_points is None:
                estimated = self._estimate_points(contexts)
                if estimated is None and self._config.use_mock_embeddings:
                    estimated = fallback
                if estimated is not None:
                    task.story_points = estimated
                    if "rag-estimated" not in task.labels:
                        task.labels.append("rag-estimated")
        return {"tasks": tasks, "contexts_by_task": contexts_by_task}

    def _node_improve_description(self, state: RAGPipelineState) -> dict[str, Any]:
        tasks = list(state.get("tasks") or [])
        contexts_by_task = dict(state.get("contexts_by_task") or {})
        for idx, task in enumerate(tasks):
            contexts = contexts_by_task.get(idx, [])
            improved = (self._llm_improve_description(task, contexts) or "").strip()
            if improved and improved != (task.description or "").strip():
                task.description = improved
                if "rag-description-enhanced" not in task.labels:
                    task.labels.append("rag-description-enhanced")
        return {"tasks": tasks}

    @staticmethod
    def _context_payload(ctx: RetrievedContext) -> dict[str, Any]:
        metadata = dict(ctx.metadata)
        return {
            "score": ctx.score,
            "metadata": metadata,
            "preview": (ctx.text or "")[:300],
        }

    def _run_pipeline(self, state: RAGPipelineState) -> RAGPipelineState:
        if self._pipeline_graph:
            return self._pipeline_graph.invoke(state)
        state = dict(state)
        state.update(self._node_collect_old_tasks(state))
        state.update(self._node_collect_confluence_data(state))
        state.update(self._node_collect_transcript_data(state))
        state.update(self._node_build_knowledge_base(state))
        state.update(self._node_estimate_points(state))
        state.update(self._node_improve_description(state))
        return state

    def enrich(
        self,
        *,
        transcript: str,
        result: ExtractionResult,
        history_tasks: Iterable[Mapping[str, Any]] | None = None,
        meeting_id: str | None = None,
        project_key: str | None = None,
        owner_id: str | None = None,  # reserved for future tenant scoping
        confluence_access_token: str | None = None,
    ) -> tuple[ExtractionResult, dict]:
        del owner_id  # currently unused, retained for API compatibility
        started = time.perf_counter()
        history_rows = list(history_tasks or [])

        initial_state: RAGPipelineState = {
            "transcript": transcript,
            "meeting_id": meeting_id,
            "project_key": project_key,
            "confluence_access_token": confluence_access_token,
            "tasks": list(result.tasks),
            "history_rows": history_rows,
        }
        out = self._run_pipeline(initial_state)
        tasks = list(out.get("tasks") or [])
        contexts_by_task = dict(out.get("contexts_by_task") or {})

        story_points_estimated = sum(1 for task in tasks if "rag-estimated" in (task.labels or []))
        description_enhanced = sum(1 for task in tasks if "rag-description-enhanced" in (task.labels or []))
        stats: dict[str, Any] = {
            "tasks_total": len(tasks),
            "story_points_estimated": story_points_estimated,
            "story_points_kept": max(0, len(tasks) - story_points_estimated),
            "description_enhanced": description_enhanced,
            "retrievals": [],
            "top_k": self._config.top_k,
            "rerank_top_k": self._config.rerank_top_k,
            "seeded_confluence": len(out.get("confluence_docs") or []),
            "ingested_history": len(out.get("old_task_docs") or []),
            "ingested_transcript_chunks": len(out.get("transcript_docs") or []),
        }

        for idx, task in enumerate(tasks):
            contexts = contexts_by_task.get(idx, [])
            stats["retrievals"].append(
                {
                    "task_summary": task.summary,
                    "estimated_points": task.story_points,
                    "contexts": [self._context_payload(ctx) for ctx in contexts],
                }
            )

        stats["latency_ms_retrieval"] = (time.perf_counter() - started) * 1000
        return ExtractionResult(tasks=tasks), stats


def write_stats(stats: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
