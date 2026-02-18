from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from backend.infrastructure.llm.task_extractor import LLMExtractor


def make_graph(_config=None) -> CompiledStateGraph:
    extractor = LLMExtractor()
    # LangGraph API manages persistence; avoid custom checkpointers here.
    extractor._checkpointer = None
    graph = extractor._build_graph()
    if graph is None:
        raise RuntimeError("LangGraph runtime is disabled. Set AGENT_RUNTIME=langgraph.")
    return graph


graph = make_graph()
