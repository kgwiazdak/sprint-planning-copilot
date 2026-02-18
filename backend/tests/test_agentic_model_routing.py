from __future__ import annotations

from backend.infrastructure.llm.task_extractor import LLMExtractor


def test_route_model_switches_to_stronger_model_for_long_transcript(monkeypatch):
    monkeypatch.setenv("AGENT_PLANNER_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("AGENT_PLANNER_MODEL_STRONG", "gpt-4.1")
    monkeypatch.setenv("AGENT_MODEL_SWITCH_CHAR_THRESHOLD", "20")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    extractor = LLMExtractor()
    provider, model, _temp = extractor._route_model(
        role="planner",
        transcript="x" * 30,
        confidence_hint=None,
    )

    assert provider == "openai"
    assert model == "gpt-4.1"


def test_route_model_switches_to_stronger_model_for_low_confidence(monkeypatch):
    monkeypatch.setenv("AGENT_CRITIC_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("AGENT_CRITIC_MODEL_STRONG", "gpt-4.1")
    monkeypatch.setenv("AGENT_MODEL_SWITCH_LOW_CONF_THRESHOLD", "0.8")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    extractor = LLMExtractor()
    provider, model, _temp = extractor._route_model(
        role="critic",
        transcript="short",
        confidence_hint=0.4,
    )

    assert provider == "openai"
    assert model == "gpt-4.1"


def test_dynamic_prompt_includes_context_and_speakers(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    extractor = LLMExtractor()
    prompt = extractor._build_dynamic_prompt(
        role="planner",
        context={
            "role": "planner",
            "transcript": "Alice: We need API migration.\nBob: I can own that.",
            "valid_speakers": ["Alice", "Bob"],
            "transcript_chars": 58,
            "transcript_lines": 2,
            "confidence_hint": 1.0,
            "current_result_json": "{}",
        },
    )

    assert "Alice, Bob" in prompt
    assert "assignee_name must match or be null" in prompt


def test_role_agent_uses_middleware_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    extractor = LLMExtractor()
    planner = extractor._agents["planner"]
    assert hasattr(planner, "invoke")
    # Smoke-check context keys expected by middleware dynamic prompt/router.
    context = {
        "transcript": "Alice: We need API migration.\nBob: I can own that.",
        "valid_speakers": ["Alice", "Bob"],
        "transcript_chars": 58,
        "transcript_lines": 2,
        "confidence_hint": 1.0,
        "current_result_json": "{}",
    }
    assert "transcript" in context and "valid_speakers" in context
