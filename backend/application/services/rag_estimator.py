from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

from backend.schemas import ExtractionResult, Task


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    # simple word tokenizer: alphanumerics only
    return re.findall(r"[a-z0-9]+", text)


def _tf(counter: Counter[str]) -> dict[str, float]:
    total = sum(counter.values()) or 1
    return {k: v / total for k, v in counter.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    num = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    denom = math.sqrt(sum((a.get(k, 0.0)) ** 2 for k in keys)) * math.sqrt(sum((b.get(k, 0.0)) ** 2 for k in keys))
    return num / denom if denom else 0.0


@dataclass
class CorpusDoc:
    doc_id: str
    title: str
    text: str
    points: int | None = None


class RAGEstimator:
    """
    Lightweight, dependency-free retrieval+estimation against local Confluence markdown and historical tasks.
    - Uses bag-of-words cosine similarity to find comparable items.
    - Does not overwrite explicit points.
    """

    def __init__(self, confluence_dir: str = "mock_confluence") -> None:
        self._confluence_dir = Path(confluence_dir)
        self._corpus: list[CorpusDoc] = []
        self._load_confluence()

    def _load_confluence(self) -> None:
        if not self._confluence_dir.exists():
            return
        for path in self._confluence_dir.glob("*.md"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            self._corpus.append(CorpusDoc(doc_id=path.name, title=path.stem, text=text))

    def _build_vector(self, text: str) -> dict[str, float]:
        tokens = _tokenize(text)
        return _tf(Counter(tokens))

    def _score(self, query_vec: dict[str, float], doc_vecs: list[tuple[CorpusDoc, dict[str, float]]]) -> list[tuple[CorpusDoc, float]]:
        scored: list[tuple[CorpusDoc, float]] = []
        for doc, vec in doc_vecs:
            scored.append((doc, _cosine(query_vec, vec)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _history_docs(self, history_tasks: Iterable[dict]) -> list[CorpusDoc]:
        docs: list[CorpusDoc] = []
        for task in history_tasks:
            summary = task.get("summary") or ""
            description = task.get("description") or ""
            points = task.get("storyPoints")
            text = f"{summary}\n{description}"
            docs.append(CorpusDoc(doc_id=task.get("id", ""), title=summary[:80], text=text, points=points))
        return docs

    def enrich(self, *, transcript: str, result: ExtractionResult, history_tasks: Iterable[dict] | None = None) -> tuple[ExtractionResult, dict]:
        """
        Returns updated result with story_points filled when missing + metadata stats.
        """
        history_docs = self._history_docs(history_tasks or [])
        doc_vecs = [(doc, self._build_vector(doc.text)) for doc in (self._corpus + history_docs)]
        stats = {"tasks_total": len(result.tasks), "estimated": 0, "kept": 0, "refused": 0}
        new_tasks: list[Task] = []
        for task in result.tasks:
            if task.story_points is not None:
                stats["kept"] += 1
                new_tasks.append(task)
                continue
            query_text = f"{task.summary}\n{task.description}"
            qvec = self._build_vector(query_text)
            scored = self._score(qvec, doc_vecs)[:5]
            top_points = [doc.points for doc, score in scored if doc.points is not None and score > 0.05]
            est_points = None
            if top_points:
                est_points = round(sum(top_points) / len(top_points))
            else:
                stats["refused"] += 1
            if est_points is not None:
                task.story_points = est_points
                stats["estimated"] += 1
            new_tasks.append(task)
        updated = ExtractionResult(tasks=new_tasks)
        return updated, stats


def write_stats(stats: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
