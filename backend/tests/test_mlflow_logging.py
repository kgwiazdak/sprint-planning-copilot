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
