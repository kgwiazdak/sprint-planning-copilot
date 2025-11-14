from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence

try:  # pragma: no cover - optional dependency guard
    import mlflow
    from mlflow.exceptions import MlflowException
    from mlflow.tracking import MlflowClient
except ModuleNotFoundError:  # pragma: no cover - fallback for local dev without mlflow
    class MlflowException(RuntimeError):
        """Placeholder raised when MLflow is unavailable."""

    class MlflowClient:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            raise RuntimeError("MlflowClient requires the 'mlflow' package to be installed")

    class _MlflowStub:
        def __getattr__(self, name):  # noqa: D401
            def _missing(*args, **kwargs):
                raise RuntimeError(f"mlflow.{name} requires the 'mlflow' package to be installed")

            return _missing

    mlflow = _MlflowStub()  # type: ignore[assignment]
from pydantic import BaseModel, ValidationError

from backend.schemas import ExtractionResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

DEFAULT_EXPERIMENT_NAME = "ai-scrum-copilot-mvp"
TRANSCRIPT_SNIPPET_CHARS = int(os.getenv("TRANSCRIPT_SNIPPET_CHARS", "4000"))
MAX_TRANSCRIPT_CHARS = int(os.getenv("MLFLOW_TRANSCRIPT_MAX_CHARS", "200000"))
ARTIFACT_COMPRESS_THRESHOLD = int(os.getenv("MLFLOW_ARTIFACT_COMPRESS_THRESHOLD", "200000"))
SCHEMA_VERSION = os.getenv("EXTRACTION_SCHEMA_VERSION", "2024-09-01")
ASSIGNEE_MAPPING_VERSION = os.getenv("ASSIGNEE_MAPPING_VERSION", "v1")
PROMPT_TEMPLATE_ID = os.getenv("PROMPT_TEMPLATE_ID", "default-template")
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "v1")
RUN_PHASES = ("transcription", "extraction", "normalization", "approval", "push_to_jira", "reports")
SENSITIVE_KEYS = ("api_key", "apikey", "token", "secret", "password", "connection_string")
SECRET_VALUE_REGEX = re.compile(r"(?i)(api_key|token|secret|password|connection_string)\s*[:=]\s*([A-Za-z0-9\-_/+=]{6,})")
LATENCY_ACCUMULATION_KEYS = {
    "latency_ms_transcribe",
    "latency_ms_llm",
    "latency_ms_normalization",
    "latency_ms_approval",
    "latency_ms_push",
}
SLO_LATENCY_MS = int(os.getenv("SLO_LATENCY_MS", "10000"))
COST_BUDGET_USD = float(os.getenv("COST_BUDGET_USD", "10"))
APPROVAL_RATE_THRESHOLD = float(os.getenv("APPROVAL_RATE_THRESHOLD", "0.75"))
PII_REDACTION_MODE = os.getenv("PII_REDACTION_MODE", "balanced")


class PayloadSerializationError(RuntimeError):
    """Raised when result payload cannot be serialized."""


class RunCreationError(RuntimeError):
    """Raised when MLflow run could not be started."""


class ArtifactLoggingError(RuntimeError):
    """Raised when artifacts fail to upload to MLflow."""


@dataclass
class LoggedRunInfo:
    run_id: str
    run_url: str
    experiment_id: str


@dataclass
class ArtifactRecord:
    path: str
    content: Any
    is_json: bool = False
    compressible: bool = True


@dataclass
class PhaseData:
    name: str
    metrics: dict[str, float] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    artifacts: list[ArtifactRecord] = field(default_factory=list)


class BasePIIRedactor:
    def redact(self, text: str) -> tuple[str, list[str]]:  # pragma: no cover - interface only
        raise NotImplementedError


class RegexPIIRedactor(BasePIIRedactor):
    """Fallback regex-based redactor used when Presidio is unavailable."""

    EMAIL_PATTERN = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    PHONE_PATTERN = r"\+?\d[\d\s().-]{8,}"

    def __init__(self, mode: str):
        self.mode = mode
        self._patterns = [
            (self.EMAIL_PATTERN, "[REDACTED_EMAIL]"),
            (self.PHONE_PATTERN, "[REDACTED_PHONE]"),
        ]

    def redact(self, text: str) -> tuple[str, list[str]]:
        import re

        rules: list[str] = []
        redacted = text
        for pattern, replacement in self._patterns:
            compiled = re.compile(pattern)
            if compiled.search(redacted):
                rules.append(pattern)
                redacted = compiled.sub(replacement, redacted)
        return redacted, rules


try:  # pragma: no cover - optional dependency
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
except ImportError:  # pragma: no cover - fallback handled below
    AnalyzerEngine = None
    AnonymizerEngine = None


class PresidioPIIRedactor(BasePIIRedactor):
    """Presidio-powered redactor when the library is available."""

    def __init__(self, mode: str):
        if AnalyzerEngine is None or AnonymizerEngine is None:
            raise RuntimeError("Presidio is not installed")
        self.mode = mode
        self._analyzer = AnalyzerEngine()
        self._anonymizer = AnonymizerEngine()

    def redact(self, text: str) -> tuple[str, list[str]]:
        language = os.getenv("PII_LANGUAGE", "en")
        entities = os.getenv("PII_ENTITIES")
        entities_list = [e.strip() for e in entities.split(",") if e.strip()] if entities else None
        results = self._analyzer.analyze(text=text, language=language, entities=entities_list)
        if not results:
            return text, []
        anonymized = self._anonymizer.anonymize(text=text, analyzer_results=results)
        rules = sorted({result.entity_type for result in results})
        return anonymized.text, rules


def log_extraction_run(
    meeting_id: str,
    run_id: str,
    transcript: str,
    result: ExtractionResult | BaseModel | Mapping[str, Any],
    *,
    meeting_date: str | None = None,
    transcript_blob_uri: str | None = None,
    transcript_language: str | None = None,
    telemetry: Mapping[str, Any] | None = None,
    diarization_payload: Mapping[str, Any] | None = None,
) -> LoggedRunInfo | None:
    """Log the extraction pipeline execution to MLflow and return run metadata."""

    setup = _configure_mlflow()
    if setup is None:
        logger.warning("MLflow not configured; skipping logging for meeting_id=%s run_id=%s", meeting_id, run_id)
        return None

    _enforce_azure_artifact_requirements()

    telemetry = telemetry or {}
    meeting_date = meeting_date or date.today().isoformat()
    transcript_blob_uri = transcript_blob_uri or "unknown"
    transcript_language = transcript_language or telemetry.get("transcription", {}).get("language", "unknown")

    redactor = _build_redactor()
    redacted_snippet, rules = _prepare_transcript_snippet(transcript or "", redactor)

    prompt_template = _resolve_prompt_template()
    prompt_hash = _hash_prompt(prompt_template)

    try:
        raw_payload = _coerce_payload(result)
    except PayloadSerializationError as exc:
        logger.error("Unable to serialize payload for meeting_id=%s run_id=%s: %s", meeting_id, run_id, exc)
        return None

    is_valid, normalized_payload = _validate_payload(raw_payload)
    tasks_extracted = len(normalized_payload.get("tasks", [])) if is_valid else len(raw_payload.get("tasks", []))
    json_valid_rate = 1.0 if is_valid else 0.0
    approval_stats = _compute_approval_stats(raw_payload)
    diff_stats = _compute_edit_distance_stats(raw_payload, normalized_payload)

    pipeline_version = _get_pipeline_version()
    params = _build_core_params(
        meeting_id=meeting_id,
        run_id=run_id,
        meeting_date=meeting_date,
        transcript_language=transcript_language,
        transcript_blob_uri=transcript_blob_uri,
        prompt_hash=prompt_hash,
        prompt_template=prompt_template,
        pii_mode=PII_REDACTION_MODE,
        pii_rules=rules,
        pipeline_version=pipeline_version,
    )

    tags = _build_tags(meeting_id)
    phase_data = _build_phase_data(
        telemetry=telemetry,
        transcript_snippet=redacted_snippet,
        diarization_payload=diarization_payload or {},
        raw_payload=raw_payload,
        normalized_payload=normalized_payload,
        approval_stats=approval_stats,
        diff_stats=diff_stats,
        prompt_template=prompt_template,
        json_valid_rate=json_valid_rate,
        is_valid=is_valid,
        transcript_blob_uri=transcript_blob_uri,
        transcript_language=transcript_language,
    )

    aggregate_metrics = _build_aggregate_metrics(phase_data, tasks_extracted, json_valid_rate, approval_stats)
    alerts = _derive_alerts(
        json_valid_rate=json_valid_rate,
        approval_stats=approval_stats,
        aggregate_metrics=aggregate_metrics,
    )
    tags.update(alerts["tags"])  # record alert tags for filtering
    aggregate_metrics.update(alerts["metrics"])

    run_name = f"{meeting_id}-{run_id}"
    run_name, revision = _ensure_unique_run_name(run_name, meeting_id, setup.experiment_id)
    if revision:
        params["run_revision"] = revision

    try:
        with mlflow.start_run(run_name=run_name, tags=tags) as active_run:
            mlflow.set_tag("experiment_id", setup.experiment_id)
            _log_params_with_retry(params)
            _log_metrics_with_retry(aggregate_metrics)
            _log_schema_contract()

            for phase in phase_data:
                _log_phase_run(phase, tags, run_name)

            report_html = _build_html_summary(
                normalized_payload=normalized_payload,
                approval_stats=approval_stats,
                diff_stats=diff_stats,
                alerts=alerts,
            )
            _log_artifact_content(
                ArtifactRecord(path="artifacts/reports/run_summary.html", content=report_html, is_json=False, compressible=False)
            )

            run_url = _build_run_url(setup.tracking_uri, setup.experiment_id, active_run.info.run_id)
            mlflow.set_tag("mlflow.run_url", run_url)
            logger.info(
                "Logged MLflow run for meeting_id=%s db_run_id=%s mlflow_run_id=%s", meeting_id, run_id, active_run.info.run_id
            )
            return LoggedRunInfo(run_id=active_run.info.run_id, run_url=run_url, experiment_id=setup.experiment_id)
    except MlflowException as exc:
        logger.exception("Failed to start/log MLflow run for meeting_id=%s run_id=%s", meeting_id, run_id)
        raise RunCreationError(str(exc)) from exc
    except ArtifactLoggingError as exc:
        logger.exception("Artifact logging failed for meeting_id=%s run_id=%s: %s", meeting_id, run_id, exc)
        return None
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Unexpected MLflow logging failure for meeting_id=%s run_id=%s: %s", meeting_id, run_id, exc)
        return None


@dataclass
class MlflowSetup:
    experiment_id: str
    tracking_uri: str


def _build_phase_data(
    *,
    telemetry: Mapping[str, Any],
    transcript_snippet: str,
    diarization_payload: Mapping[str, Any],
    raw_payload: Mapping[str, Any],
    normalized_payload: Mapping[str, Any],
    approval_stats: Mapping[str, Any],
    diff_stats: Mapping[str, Any],
    prompt_template: str,
    json_valid_rate: float,
    is_valid: bool,
    transcript_blob_uri: str,
    transcript_language: str,
) -> list[PhaseData]:
    transcription_metrics = telemetry.get("transcription", {})
    extraction_metrics = telemetry.get("extraction", {})
    normalization_metrics = telemetry.get("normalization", {})
    approval_metrics = telemetry.get("approval", {})
    push_metrics = telemetry.get("push_to_jira", {})

    approval_metrics = {**approval_metrics, **approval_stats, **diff_stats.get("averages", {})}

    phases: list[PhaseData] = [
        PhaseData(
            name="transcription",
            metrics=
            {
                "audio_duration_sec": float(transcription_metrics.get("audio_duration_sec", 0.0)),
                "latency_ms_transcribe": float(transcription_metrics.get("latency_ms_transcribe", 0.0)),
                "speaker_count": float(transcription_metrics.get("speaker_count", 0.0)),
            },
            params={"language": transcript_language or transcription_metrics.get("language", "unknown")},
            artifacts=[
                ArtifactRecord(
                    "artifacts/transcription/transcript_redacted.txt",
                    transcript_snippet,
                    is_json=False,
                    compressible=False,
                ),
                ArtifactRecord(
                    "artifacts/transcription/diarization.json",
                    diarization_payload or {},
                    is_json=True,
                ),
                ArtifactRecord(
                    "artifacts/transcription/blob_uri.txt",
                    transcript_blob_uri,
                    is_json=False,
                    compressible=False,
                ),
            ],
        ),
        PhaseData(
            name="extraction",
            metrics={
                "latency_ms_llm": float(extraction_metrics.get("latency_ms_llm", 0.0)),
                "tokens_prompt": float(extraction_metrics.get("tokens_prompt", 0.0)),
                "tokens_completion": float(extraction_metrics.get("tokens_completion", 0.0)),
                "cost_usd": float(extraction_metrics.get("cost_usd", 0.0)),
            },
            params={
                "llm_provider": extraction_metrics.get("llm_provider", os.getenv("LLM_PROVIDER", "azure")),
                "llm_model_name": extraction_metrics.get("llm_model_name", _get_llm_model_name()),
                "llm_model_version": extraction_metrics.get("llm_model_version", os.getenv("LLM_MODEL_VERSION", "unknown")),
            },
            artifacts=[
                ArtifactRecord("artifacts/extraction/raw.json", raw_payload, is_json=True),
                ArtifactRecord("artifacts/extraction/prompt.txt", prompt_template, is_json=False, compressible=False),
            ],
        ),
        PhaseData(
            name="normalization",
            metrics={"json_valid_rate": float(json_valid_rate)},
            params={"mapping_version": os.getenv("MAPPING_VERSION", "default"), "schema_version": SCHEMA_VERSION},
            artifacts=[
                ArtifactRecord("artifacts/normalization/normalized.json", normalized_payload, is_json=True),
                ArtifactRecord(
                    "artifacts/normalization/mapping.json",
                    {"schema_version": SCHEMA_VERSION, "assignee_mapping_version": ASSIGNEE_MAPPING_VERSION},
                    is_json=True,
                ),
                *(
                    [
                        ArtifactRecord(
                            "artifacts/normalization/invalid_payload.json",
                            raw_payload,
                            is_json=True,
                        )
                    ]
                    if not is_valid
                    else []
                ),
            ],
        ),
        PhaseData(
            name="approval",
            metrics={
                "tasks_approved": float(approval_metrics.get("tasks_approved", 0.0)),
                "approval_rate": float(approval_metrics.get("approval_rate", 0.0)),
                "edit_distance_summary": float(approval_metrics.get("edit_distance_summary", 0.0)),
                "edit_distance_description": float(approval_metrics.get("edit_distance_description", 0.0)),
            },
            artifacts=[
                ArtifactRecord("artifacts/approval/approved.json", approval_stats.get("approved", []), is_json=True),
                ArtifactRecord("artifacts/approval/edits_diff.json", diff_stats, is_json=True),
            ],
        ),
        PhaseData(
            name="push_to_jira",
            metrics={
                "issues_created": float(push_metrics.get("issues_created", 0.0)),
                "issues_failed": float(push_metrics.get("issues_failed", 0.0)),
                "retry_count": float(push_metrics.get("retry_count", 0.0)),
                "latency_ms_push": float(push_metrics.get("latency_ms_push", 0.0)),
                "latency_ms_p95": float(push_metrics.get("latency_ms_p95", 0.0)),
            },
            artifacts=[
                ArtifactRecord(
                    "artifacts/push_to_jira/status_histogram.json",
                    push_metrics.get("status_histogram", {}),
                    is_json=True,
                ),
            ],
        ),
    ]
    phase_order = {name: index for index, name in enumerate(RUN_PHASES)}
    phases.sort(key=lambda phase: phase_order.get(phase.name, len(RUN_PHASES)))
    return phases


def _build_core_params(
    *,
    meeting_id: str,
    run_id: str,
    meeting_date: str,
    transcript_language: str,
    transcript_blob_uri: str,
    prompt_hash: str,
    prompt_template: str,
    pii_mode: str,
    pii_rules: Sequence[str],
    pipeline_version: str,
) -> dict[str, Any]:
    llm_temperature = os.getenv("LLM_TEMPERATURE", "0.1")
    params: dict[str, Any] = {
        "meeting_id": meeting_id,
        "app_run_id": run_id,
        "meeting_date": meeting_date,
        "project_key": os.getenv("PROJECT_KEY", "UNKNOWN"),
        "language": transcript_language,
        "pipeline_version": pipeline_version,
        "assignee_mapping_version": ASSIGNEE_MAPPING_VERSION,
        "prompt_template_id": PROMPT_TEMPLATE_ID,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": prompt_hash,
        "transcript_blob_uri": transcript_blob_uri,
        "pii_redaction_mode": pii_mode,
        "pii_rules_applied": ",".join(sorted(pii_rules)) or "none",
        "llm_model_name": _get_llm_model_name(),
        "llm_temperature": llm_temperature,
    }
    if os.getenv("ENVIRONMENT") == "prod" and not os.getenv("PIPELINE_VERSION"):
        raise RuntimeError("PIPELINE_VERSION must be set in production environments")
    return params


def _build_tags(meeting_id: str) -> MutableMapping[str, str]:
    environment = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "dev"))
    tags: dict[str, str] = {
        "app": os.getenv("APP_NAME", "ai-scrum-copilot"),
        "env": environment,
        "meeting_id": meeting_id,
        "llm_provider": os.getenv("LLM_PROVIDER", "azure"),
        "step": "extraction",
    }
    return tags


def _build_aggregate_metrics(
    phase_data: Iterable[PhaseData],
    tasks_extracted: int,
    json_valid_rate: float,
    approval_stats: Mapping[str, Any],
) -> dict[str, float]:
    total_latency = 0.0
    total_cost = 0.0
    metrics: dict[str, float] = {"tasks_extracted": float(tasks_extracted), "json_valid_rate": json_valid_rate}
    for phase in phase_data:
        for key, value in phase.metrics.items():
            metrics.setdefault(key, 0.0)
            metrics[key] = value
            if key in LATENCY_ACCUMULATION_KEYS:
                total_latency += value
            if key.startswith("cost_usd") or key == "cost_usd":
                total_cost += value
    metrics["latency_ms_total"] = total_latency
    metrics["cost_usd_total"] = total_cost
    metrics["approval_rate"] = float(approval_stats.get("approval_rate", 0.0))
    metrics["tasks_approved"] = float(approval_stats.get("tasks_approved", 0.0))
    return metrics


def _build_html_summary(
    *,
    normalized_payload: Mapping[str, Any],
    approval_stats: Mapping[str, Any],
    diff_stats: Mapping[str, Any],
    alerts: Mapping[str, Any],
) -> str:
    tasks_preview = "".join(
        f"<li>{_scrub_secrets(task.get('summary', 'missing summary'))}</li>" for task in normalized_payload.get("tasks", [])[:10]
    )
    alerts_list = "".join(f"<li>{name}: {value}</li>" for name, value in alerts.get("flags", {}).items())
    return (
        "<html><body>"
        "<h1>Run Summary</h1>"
        f"<p>Tasks logged: {len(normalized_payload.get('tasks', []))}</p>"
        "<h2>Alerts</h2>"
        f"<ul>{alerts_list or '<li>None</li>'}</ul>"
        "<h2>Sample Tasks</h2>"
        f"<ul>{tasks_preview}</ul>"
        "<h2>Approval Stats</h2>"
        f"<pre>{json.dumps(approval_stats, indent=2)}</pre>"
        "<h2>Edit Distance</h2>"
        f"<pre>{json.dumps(diff_stats, indent=2)}</pre>"
        "</body></html>"
    )


def _resolve_prompt_template() -> str:
    template_path = os.getenv("PROMPT_TEMPLATE_PATH")
    if template_path and Path(template_path).exists():
        return Path(template_path).read_text(encoding="utf-8")
    return os.getenv(
        "PROMPT_TEMPLATE_DEFAULT",
        "You are an Agile Product Owner. Extract Jira-ready tasks from meeting transcripts using the schema provided.",
    )


def _hash_prompt(template: str) -> str:
    llm_config = _get_llm_model_name()
    payload = f"{template}::{llm_config}::{os.getenv('LLM_TEMPERATURE', '0.1')}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _scrub_secrets(text: str) -> str:
    redacted = text
    for key in SENSITIVE_KEYS:
        redacted = redacted.replace(key, "[REDACTED]")

    def _mask(match: re.Match[str]) -> str:
        return f"{match.group(1)}=[REDACTED]"

    return SECRET_VALUE_REGEX.sub(_mask, redacted)


def _prepare_transcript_snippet(transcript: str, redactor: BasePIIRedactor) -> tuple[str, list[str]]:
    snippet_source = transcript[: min(MAX_TRANSCRIPT_CHARS, len(transcript))]
    snippet = snippet_source[:TRANSCRIPT_SNIPPET_CHARS]
    redacted_snippet, rules = redactor.redact(snippet)
    cleaned = _scrub_secrets(redacted_snippet)
    return cleaned[:TRANSCRIPT_SNIPPET_CHARS], rules


def _compute_approval_stats(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    approved = payload.get("approved")
    if not isinstance(approved, list):
        approved = []
    tasks = payload.get("tasks")
    total = len(tasks) if isinstance(tasks, list) else 0
    tasks_approved = len(approved)
    approval_rate = float(tasks_approved / total) if total else 0.0
    return {"approved": approved, "tasks_approved": tasks_approved, "approval_rate": approval_rate}


def _compute_edit_distance_stats(
    raw_payload: Mapping[str, Any],
    normalized_payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    from difflib import SequenceMatcher

    raw_tasks = raw_payload.get("tasks") or []
    norm_tasks = normalized_payload.get("tasks") or []
    total_summary = 0.0
    total_description = 0.0
    count = min(len(raw_tasks), len(norm_tasks)) or 1
    details = []
    for raw_task, norm_task in zip(raw_tasks, norm_tasks):
        raw_summary = raw_task.get("summary", "")
        norm_summary = norm_task.get("summary", "")
        raw_description = raw_task.get("description", "")
        norm_description = norm_task.get("description", "")
        summary_distance = 1 - SequenceMatcher(None, raw_summary, norm_summary).ratio()
        description_distance = 1 - SequenceMatcher(None, raw_description, norm_description).ratio()
        total_summary += summary_distance
        total_description += description_distance
        details.append(
            {
                "raw_summary": raw_summary,
                "normalized_summary": norm_summary,
                "summary_distance": summary_distance,
                "raw_description": raw_description,
                "normalized_description": norm_description,
                "description_distance": description_distance,
            }
        )

    averages = {
        "edit_distance_summary": total_summary / count,
        "edit_distance_description": total_description / count,
    }
    return {"averages": averages, "details": details}


def _derive_alerts(
    *,
    json_valid_rate: float,
    approval_stats: Mapping[str, Any],
    aggregate_metrics: Mapping[str, float],
) -> Mapping[str, Any]:
    flags: dict[str, Any] = {}
    metrics: dict[str, float] = {}
    if json_valid_rate < 1.0:
        flags["json_valid_rate"] = "schema validation failed"
        metrics["alert_json_valid_rate"] = 1.0
    approval_rate = float(approval_stats.get("approval_rate", 0.0))
    if approval_rate < APPROVAL_RATE_THRESHOLD:
        flags["approval_rate"] = f"approval rate {approval_rate:.2f} below threshold {APPROVAL_RATE_THRESHOLD}"
        metrics["alert_approval_rate"] = 1.0
    latency_ms_total = float(aggregate_metrics.get("latency_ms_total", 0.0))
    if latency_ms_total > SLO_LATENCY_MS:
        flags["latency_ms_total"] = f"latency {latency_ms_total}ms breaching SLO {SLO_LATENCY_MS}"
        metrics["alert_latency_ms_total"] = 1.0
    cost_usd_total = float(aggregate_metrics.get("cost_usd_total", 0.0))
    if cost_usd_total > COST_BUDGET_USD:
        flags["cost_usd_total"] = f"cost ${cost_usd_total:.2f} over budget ${COST_BUDGET_USD:.2f}"
        metrics["alert_cost_usd_total"] = 1.0
    return {"flags": flags, "metrics": metrics, "tags": {f"alert_{key}": "true" for key in flags}}


def _log_phase_run(phase: PhaseData, parent_tags: Mapping[str, str], parent_run_name: str) -> None:
    phase_tags = dict(parent_tags)
    phase_tags["step"] = phase.name
    try:
        with mlflow.start_run(run_name=f"{parent_run_name}-{phase.name}", nested=True, tags=phase_tags):
            if phase.params:
                _log_params_with_retry(phase.params)
            if phase.metrics:
                _log_metrics_with_retry(phase.metrics)
            for artifact in phase.artifacts:
                _log_artifact_content(artifact)
    except MlflowException as exc:
        logger.warning("Unable to log nested MLflow run '%s': %s", phase.name, exc)


def _log_artifact_content(record: ArtifactRecord) -> None:
    if record.is_json:
        content = json.dumps(record.content, ensure_ascii=False, indent=2)
    else:
        content = str(record.content)
    _log_text_or_compressed(content, record.path, record.compressible)


def _log_text_or_compressed(content: str, artifact_rel_path: str, compressible: bool) -> None:
    text = _scrub_secrets(content)
    data = text.encode("utf-8")
    filename = Path(artifact_rel_path).name
    artifact_dir = str(Path(artifact_rel_path).parent)
    use_compression = compressible and len(data) > ARTIFACT_COMPRESS_THRESHOLD
    if use_compression:
        data = gzip.compress(data)
        filename = f"{filename}.gz"
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = Path(tmpdir) / filename
        temp_path.write_bytes(data)
        try:
            _retry(lambda: mlflow.log_artifact(str(temp_path), artifact_path=artifact_dir))
        except Exception as exc:
            raise ArtifactLoggingError(str(exc)) from exc


def _log_params_with_retry(params: Mapping[str, Any]) -> None:
    clean = _clean_mapping(params)
    if clean:
        _retry(lambda: mlflow.log_params(clean))


def _log_metrics_with_retry(metrics: Mapping[str, float]) -> None:
    clean = {key: float(value) for key, value in metrics.items() if value is not None}
    if clean:
        _retry(lambda: mlflow.log_metrics(clean))


def _log_schema_contract() -> None:
    _retry(lambda: mlflow.log_param("schema_version", SCHEMA_VERSION))


def _clean_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if value is not None}


def _coerce_payload(result: ExtractionResult | BaseModel | Mapping[str, Any]) -> Mapping[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "dict"):
        return result.dict()
    if isinstance(result, Mapping):
        return dict(result)
    raise PayloadSerializationError("Unsupported result payload type")


def _validate_payload(payload: Mapping[str, Any]) -> tuple[bool, Mapping[str, Any]]:
    try:
        validated = ExtractionResult.model_validate(payload)
        return True, validated.model_dump()
    except ValidationError:
        logger.warning("Extraction payload failed schema validation; logging raw payload only.")
        return False, payload

def _build_redactor() -> BasePIIRedactor:
    preferred = os.getenv("PII_REDACTOR", "presidio").lower()
    if preferred == "presidio":
        try:
            return PresidioPIIRedactor(PII_REDACTION_MODE)
        except RuntimeError:
            logger.warning("Presidio redactor unavailable; falling back to regex redaction")
    return RegexPIIRedactor(PII_REDACTION_MODE)


def _get_pipeline_version() -> str:
    env_version = os.getenv("PIPELINE_VERSION")
    if env_version:
        return env_version
    try:
        output = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        return output.decode("utf-8").strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def _get_llm_model_name() -> str:
    provider = os.getenv("LLM_PROVIDER", "azure").lower()
    if provider == "azure":
        return os.getenv("AZURE_OPENAI_DEPLOYMENT", "azure-deployment-unknown")
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _enforce_azure_artifact_requirements() -> None:
    artifact_root = os.getenv("MLFLOW_DEFAULT_ARTIFACT_ROOT", "")
    if not artifact_root.startswith("wasbs://"):
        return
    has_connection_string = bool(os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
    has_access_key = bool(os.getenv("AZURE_STORAGE_ACCESS_KEY"))
    if not (has_connection_string or has_access_key):
        raise RuntimeError(
            "MLFLOW_DEFAULT_ARTIFACT_ROOT points to Azure Blob Storage but no credentials were provided."
        )


def _retry(action: Callable[[], None], attempts: int = 3, base_delay: float = 0.5) -> None:
    for attempt in range(1, attempts + 1):
        try:
            action()
            return
        except Exception:  # pragma: no cover - defensive retry
            if attempt == attempts:
                raise
            time.sleep(base_delay * attempt)


def _build_run_url(tracking_uri: str, experiment_id: str, run_id: str) -> str:
    if tracking_uri.endswith("/"):
        tracking_uri = tracking_uri[:-1]
    return f"{tracking_uri}/#/experiments/{experiment_id}/runs/{run_id}"


def _ensure_unique_run_name(base_name: str, meeting_id: str, experiment_id: str) -> tuple[str, int | None]:
    client = MlflowClient()
    filter_string = f"tags.meeting_id = '{meeting_id}'"
    try:
        runs = client.search_runs([experiment_id], filter_string=filter_string, max_results=200)
    except MlflowException:
        return base_name, None
    existing_names = {run.info.run_name for run in runs if run.info.run_name}
    if base_name not in existing_names:
        return base_name, None
    suffix = 1
    while f"{base_name}-rev{suffix}" in existing_names:
        suffix += 1
    return f"{base_name}-rev{suffix}", suffix


def _configure_mlflow() -> MlflowSetup | None:
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    token = os.getenv("MLFLOW_API_TOKEN")
    if token:
        os.environ["MLFLOW_TRACKING_TOKEN"] = token

    environment = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "dev"))
    experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", DEFAULT_EXPERIMENT_NAME)
    experiment_name = f"{experiment_name}-{environment}"
    try:
        experiment = mlflow.set_experiment(experiment_name)
    except MlflowException as exc:
        logger.error("Unable to set MLflow experiment '%s': %s", experiment_name, exc)
        return None

    resolved_tracking_uri = mlflow.get_tracking_uri()
    artifact_root = os.getenv("MLFLOW_DEFAULT_ARTIFACT_ROOT", "not-set")
    credential_mode = "connection_string" if os.getenv("AZURE_STORAGE_CONNECTION_STRING") else (
        "access_key" if os.getenv("AZURE_STORAGE_ACCESS_KEY") else (
            "managed_identity" if os.getenv("AZURE_CLIENT_ID") else "unknown"
        )
    )
    logger.info(
        "Using MLflow experiment '%s' (%s) at %s (artifact_root=%s, credential_mode=%s)",
        experiment_name,
        experiment.experiment_id,
        resolved_tracking_uri,
        artifact_root,
        credential_mode,
    )
    return MlflowSetup(experiment_id=experiment.experiment_id, tracking_uri=resolved_tracking_uri)
