from unittest.mock import patch

from backend import mlflow_logging as logging_utils


def test_validate_payload_failure_returns_raw():
    invalid_payload = {"tasks": []}
    is_valid, payload = logging_utils._validate_payload(invalid_payload)

    assert is_valid is False
    assert payload == invalid_payload


def test_regex_redactor_masks_email_and_phone():
    redactor = logging_utils.RegexPIIRedactor("balanced")
    text = "Contact me at owner@example.com or +1 555 123 4567"

    redacted, rules = redactor.redact(text)

    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted
    assert rules  # ensure at least one rule triggered


def test_prepare_transcript_snippet_truncates_and_scrubs():
    redactor = logging_utils.RegexPIIRedactor("balanced")
    long_text = "secret_token=abcdef123456" + "a" * (logging_utils.TRANSCRIPT_SNIPPET_CHARS + 50)

    snippet, rules = logging_utils._prepare_transcript_snippet(long_text, redactor)

    assert len(snippet) <= logging_utils.TRANSCRIPT_SNIPPET_CHARS
    assert "[REDACTED]" in snippet
    assert isinstance(rules, list)


def test_prepare_transcript_views_returns_full_text_and_snippet():
    redactor = logging_utils.RegexPIIRedactor("balanced")
    long_text = "owner@example.com " + "a" * (logging_utils.TRANSCRIPT_SNIPPET_CHARS + 50)

    full_text, snippet, rules = logging_utils._prepare_transcript_views(long_text, redactor)

    assert snippet == full_text[: logging_utils.TRANSCRIPT_SNIPPET_CHARS]
    assert "[REDACTED_EMAIL]" in full_text
    assert rules


def test_retry_eventual_success():
    state = {"count": 0}

    def flaky():
        state["count"] += 1
        if state["count"] < 2:
            raise RuntimeError("fail once")

    logging_utils._retry(flaky, attempts=3, base_delay=0)

    assert state["count"] == 2


def test_compute_edit_distance_stats_detects_changes():
    raw = {"tasks": [{"summary": "old", "description": "foo"}]}
    normalized = {"tasks": [{"summary": "new", "description": "foo"}]}

    stats = logging_utils._compute_edit_distance_stats(raw, normalized)

    assert stats["averages"]["edit_distance_summary"] > 0
    assert stats["averages"]["edit_distance_description"] == 0


@patch("backend.mlflow_logging.mlflow.log_param")
def test_schema_contract_logs_version(mock_log_param):
    logging_utils._log_schema_contract()

    mock_log_param.assert_called_with("schema_version", logging_utils.SCHEMA_VERSION)


def test_build_phase_data_includes_full_transcript_and_tasks_artifacts():
    phases = logging_utils._build_phase_data(
        telemetry={},
        transcript_snippet="short",
        transcript_full="secret_token=abcdef123456",
        diarization_payload={},
        raw_payload={"tasks": [{"summary": "t1"}]},
        normalized_payload={"tasks": [{"summary": "t1"}]},
        approval_stats={"approved": [], "tasks_approved": 0, "approval_rate": 0.0},
        diff_stats={"averages": {}},
        prompt_template="prompt",
        json_valid_rate=1.0,
        is_valid=True,
        transcript_blob_uri="blob://uri",
        transcript_language="en",
    )

    transcription_phase = next(phase for phase in phases if phase.name == "transcription")
    normalization_phase = next(phase for phase in phases if phase.name == "normalization")

    assert any(artifact.path.endswith("transcript_full.txt") for artifact in transcription_phase.artifacts)
    assert any(artifact.path.endswith("tasks.json") for artifact in normalization_phase.artifacts)


def test_build_aggregate_metrics_sums_duplicates():
    phases = [
        logging_utils.PhaseData(name="one", metrics={"latency_ms_llm": 100.0, "cost_usd": 1.5}),
        logging_utils.PhaseData(name="two", metrics={"latency_ms_llm": 50.0}),
    ]
    approval_stats = {"approval_rate": 0.5, "tasks_approved": 1}
    metrics = logging_utils._build_aggregate_metrics(phases, tasks_extracted=2, json_valid_rate=1.0,
                                                     approval_stats=approval_stats)
    assert metrics["latency_ms_llm"] == 150.0
    assert metrics["latency_ms_total"] == 150.0
    assert metrics["cost_usd"] == 1.5
    assert metrics["approval_rate"] == 0.5
