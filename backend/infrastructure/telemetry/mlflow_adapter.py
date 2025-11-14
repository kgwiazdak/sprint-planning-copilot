from __future__ import annotations

from backend.application.ports import TelemetryPort
from backend.mlflow_logging import log_extraction_run, logger
from backend.schemas import ExtractionResult


class MLflowTelemetryAdapter(TelemetryPort):
    """Thin adapter that proxies telemetry events to MLflow."""

    def log_extraction_run(
        self,
        *,
        meeting_id: str,
        run_id: str,
        transcript: str,
        result: ExtractionResult,
        meeting_date: str,
        transcript_blob_uri: str | None,
    ) -> None:
        try:
            log_extraction_run(
                meeting_id=meeting_id,
                run_id=run_id,
                transcript=transcript,
                result=result,
                meeting_date=meeting_date,
                transcript_blob_uri=transcript_blob_uri,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception(
                "MLflow logging failed for meeting_id=%s run_id=%s: %s",
                meeting_id,
                run_id,
                exc,
            )
