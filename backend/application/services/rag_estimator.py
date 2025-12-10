from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from llama_index.core import Document, Settings, StorageContext, VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding as LlamaMockEmbedding
from llama_index.core.llms import MockLLM
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.postprocessor import LLMRerank
from llama_index.core.schema import NodeWithScore
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI as LlamaOpenAI
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException

from backend.schemas import ExtractionResult, Task

logger = logging.getLogger(__name__)


@dataclass
class RAGConfig:
    """Configuration for the LlamaIndex-powered RAG pipeline."""

    persist_dir: Path = Path(os.getenv("RAG_INDEX_DIR", "data/rag_index"))
    qdrant_url: str | None = os.getenv("QDRANT_URL")
    qdrant_api_key: str | None = os.getenv("QDRANT_API_KEY")
    qdrant_grpc: bool = os.getenv("QDRANT_GRPC", "0").lower() in {"1", "true", "yes", "on"}
    qdrant_location: str | None = os.getenv("QDRANT_LOCATION", "data/rag_qdrant")
    collection: str = os.getenv("RAG_COLLECTION", "sprint-planning")
    confluence_dir: Path = Path(os.getenv("RAG_CONFLUENCE_DIR", "mock_confluence"))
    chunk_size: int = int(os.getenv("RAG_CHUNK_SIZE", "600"))
    chunk_overlap: int = int(os.getenv("RAG_CHUNK_OVERLAP", "80"))
    top_k: int = int(os.getenv("RAG_TOP_K", "8"))
    rerank_top_k: int = int(os.getenv("RAG_RERANK_TOP_K", "4"))
    rerank_model: str = os.getenv("RAG_RERANK_MODEL", os.getenv("RAG_LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")))
    embedding_model: str = os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-3-small")
    llm_model: str = os.getenv("RAG_LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    use_mock_embeddings: bool = field(
        default_factory=lambda: os.getenv("MOCK_RAG", "0").lower() in {"1", "true", "yes", "on"}
    )


class RAGEstimator:
    """
    Production-grade RAG pipeline powered by LlamaIndex + Chroma:
    - Persisted vector DB (Chroma) seeded with Confluence stubs and historical tasks.
    - OpenAI embeddings with optional Azure support and LLM-based reranking.
    - Story point estimation derived from the most relevant historical tasks.
    """

    def __init__(self, config: RAGConfig | None = None) -> None:
        self._config = config or RAGConfig()
        self._config.persist_dir.mkdir(parents=True, exist_ok=True)
        Settings.llm = None  # avoid accidental default OpenAI usage
        self._embed_model = self._build_embedding_model()
        self._reranker = self._build_reranker()
        self._client = self._build_chroma_client()
        self._vector_store = self._build_vector_store(self._client)
        self._storage = StorageContext.from_defaults(vector_store=self._vector_store)
        self._mock_llm = MockLLM() if self._config.use_mock_embeddings else None
        if self._mock_llm:
            Settings.llm = self._mock_llm
        self._index = VectorStoreIndex.from_vector_store(
            vector_store=self._vector_store,
            storage_context=self._storage,
            embed_model=self._embed_model,
        )
        self._node_parser = SentenceSplitter(
            chunk_size=self._config.chunk_size,
            chunk_overlap=self._config.chunk_overlap,
        )
        self._confluence_seeded = False

    def _build_chroma_client(self):
        # renamed to keep wiring minimal; builds Qdrant client.
        if self._config.use_mock_embeddings:
            return QdrantClient(location=":memory:", prefer_grpc=False)
        if self._config.qdrant_url:
            logger.info("Using remote Qdrant url=%s collection=%s", self._config.qdrant_url, self._config.collection)
            return QdrantClient(
                url=self._config.qdrant_url,
                api_key=self._config.qdrant_api_key,
                prefer_grpc=self._config.qdrant_grpc,
            )
        location = self._config.qdrant_location or str(self._config.persist_dir)
        Path(location).parent.mkdir(parents=True, exist_ok=True)
        logger.info("Using local Qdrant location=%s collection=%s", location, self._config.collection)
        return QdrantClient(location=location, prefer_grpc=False)

    def _build_vector_store(self, client: QdrantClient) -> QdrantVectorStore:
        try:
            return QdrantVectorStore(
                client=client,
                collection_name=self._config.collection,
                prefer_grpc=self._config.qdrant_grpc,
            )
        except ResponseHandlingException as exc:
            logger.warning("Qdrant unavailable (%s); falling back to in-memory store.", exc)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Qdrant init failed (%s); falling back to in-memory store.", exc)
        fallback_client = QdrantClient(location=":memory:", prefer_grpc=False)
        return QdrantVectorStore(client=fallback_client, collection_name=self._config.collection, prefer_grpc=False)

    def _build_embedding_model(self):
        if self._config.use_mock_embeddings:
            logger.info("Using mock RAG embeddings (MOCK_RAG enabled).")
            return LlamaMockEmbedding(embed_dim=128)
        provider = os.getenv("LLM_PROVIDER", "azure").lower()
        kwargs: dict[str, Any] = {"model": self._config.embedding_model}
        if provider == "azure":
            kwargs.update(
                {
                    "api_base": os.getenv("AZURE_OPENAI_ENDPOINT"),
                    "api_key": os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"),
                    "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                    "deployment": os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT")
                                  or os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                }
            )
        return OpenAIEmbedding(**kwargs)

    def _build_reranker(self) -> LLMRerank | None:
        if self._config.rerank_top_k <= 0 or self._config.use_mock_embeddings:
            return None
        try:
            provider = os.getenv("LLM_PROVIDER", "azure").lower()
            llm_kwargs: dict[str, Any] = {
                "model": self._config.rerank_model or self._config.llm_model,
                "temperature": 0.0,
            }
            api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not api_key:
                logger.info("Reranker disabled: missing OpenAI/Azure API key.")
                return None
            if provider == "azure":
                llm_kwargs.update(
                    {
                        "api_base": os.getenv("AZURE_OPENAI_ENDPOINT"),
                        "api_key": api_key,
                        "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                        "azure_deployment": os.getenv("AZURE_OPENAI_RERANK_DEPLOYMENT")
                        or os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                    }
                )
            else:
                llm_kwargs["api_key"] = api_key
            llm = LlamaOpenAI(**llm_kwargs)
            return LLMRerank(top_n=self._config.rerank_top_k, llm=llm)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Reranker disabled (fallback to vector scores): %s", exc)
            return None

    def _seed_confluence(self) -> int:
        if self._confluence_seeded or not self._config.confluence_dir.exists():
            return 0
        documents: list[Document] = []
        for path in sorted(self._config.confluence_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            documents.append(
                Document(
                    text=text,
                    metadata={
                        "source": "confluence",
                        "source_id": path.name,
                        "title": path.stem,
                    },
                    doc_id=f"confluence::{path.name}",
                )
            )
        if documents:
            nodes = self._node_parser.get_nodes_from_documents(documents)
            if nodes:
                self._index.insert_nodes(nodes)
            self._confluence_seeded = True
        return len(documents)

    def _ingest_history_tasks(self, history_tasks: Iterable[Mapping[str, Any]]) -> int:
        documents: list[Document] = []
        for task in history_tasks:
            summary = (task.get("summary") or "").strip()
            description = (task.get("description") or "").strip()
            story_points = task.get("storyPoints")
            task_id = task.get("id") or hashlib.sha256(summary.encode("utf-8")).hexdigest()
            text = f"{summary}\n\n{description}"
            documents.append(
                Document(
                    text=text,
                    metadata={
                        "source": "history",
                        "source_id": task_id,
                        "title": summary[:120],
                        "story_points": story_points,
                    },
                    doc_id=f"history::{task_id}",
                )
            )
        if documents:
            nodes = self._node_parser.get_nodes_from_documents(documents)
            if nodes:
                self._index.insert_nodes(nodes)
        return len(documents)

    def _ingest_transcript(self, transcript: str, *, meeting_id: str | None, project_key: str | None) -> int:
        base_doc = Document(
            text=transcript,
            metadata={
                "source": "transcript",
                "meeting_id": meeting_id,
                "project_key": project_key,
            },
            doc_id=f"transcript::{meeting_id or 'unknown'}",
        )
        nodes = self._node_parser.get_nodes_from_documents([base_doc])
        if nodes:
            self._index.insert_nodes(nodes)
        return len(nodes)

    def _retrieve(self, query: str) -> list[NodeWithScore]:
        postprocessors = [self._reranker] if self._reranker else []
        llm = self._mock_llm if self._mock_llm else None
        try:
            engine = self._index.as_query_engine(
                llm=llm,
                similarity_top_k=self._config.top_k,
                node_postprocessors=postprocessors,
                response_mode="no_text",
            )
            response = engine.query(query)
            return list(response.source_nodes)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("RAG retrieval failed: %s", exc)
            return []

    @staticmethod
    def _task_query(task: Task) -> str:
        return f"{task.summary}\n\n{task.description}\n\nLabels: {' '.join(task.labels)}"

    @staticmethod
    def _estimate_points_from_nodes(nodes: list[NodeWithScore]) -> int | None:
        candidates: list[int] = []
        for node in nodes:
            points = node.node.metadata.get("story_points")
            if points is None:
                continue
            try:
                candidates.append(int(points))
            except (TypeError, ValueError):
                continue
        if not candidates:
            return None
        return round(sum(candidates) / len(candidates))

    @staticmethod
    def _to_context(node: NodeWithScore) -> dict[str, Any]:
        metadata = dict(node.node.metadata)
        metadata.pop("text", None)
        return {
            "score": node.score,
            "metadata": metadata,
            "preview": (node.node.get_content() or "")[:300],
        }

    def enrich(
            self,
            *,
            transcript: str,
            result: ExtractionResult,
            history_tasks: Iterable[Mapping[str, Any]] | None = None,
            meeting_id: str | None = None,
            project_key: str | None = None,
            owner_id: str | None = None,  # kept for future tenant-aware namespaces
    ) -> tuple[ExtractionResult, dict]:
        """Populate story points and capture retrieval telemetry."""

        start = time.perf_counter()
        seeded_confluence = self._seed_confluence()
        ingested_history = self._ingest_history_tasks(history_tasks or [])
        ingested_transcript = self._ingest_transcript(transcript, meeting_id=meeting_id, project_key=project_key)

        stats: dict[str, Any] = {
            "tasks_total": len(result.tasks),
            "story_points_estimated": 0,
            "story_points_kept": 0,
            "retrievals": [],
            "top_k": self._config.top_k,
            "rerank_top_k": self._config.rerank_top_k,
            "seeded_confluence": seeded_confluence,
            "ingested_history": ingested_history,
            "ingested_transcript_chunks": ingested_transcript,
            "qdrant_target": self._config.qdrant_url or self._config.qdrant_location or "local",
        }

        updated_tasks: list[Task] = []
        for task in result.tasks:
            query = self._task_query(task)
            nodes = self._retrieve(query)
            est_points = self._estimate_points_from_nodes(nodes)
            if task.story_points is None and est_points is not None:
                task.story_points = est_points
                stats["story_points_estimated"] += 1
                if "rag-estimated" not in task.labels:
                    task.labels.append("rag-estimated")
            else:
                stats["story_points_kept"] += 1
            stats["retrievals"].append(
                {
                    "task_summary": task.summary,
                    "estimated_points": task.story_points,
                    "contexts": [self._to_context(node) for node in nodes[: self._config.rerank_top_k or self._config.top_k]],
                }
            )
            updated_tasks.append(task)

        stats["latency_ms_retrieval"] = (time.perf_counter() - start) * 1000
        return ExtractionResult(tasks=updated_tasks), stats


def write_stats(stats: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
