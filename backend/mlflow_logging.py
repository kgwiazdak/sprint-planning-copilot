import json
import logging
import os
import sys
from functools import lru_cache

logging.basicConfig(
    level=logging.INFO,  # poziom dla roota
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],  # do stdout -> docker logs
)

logger = logging.getLogger(__name__)

DEFAULT_EXPERIMENT_NAME = "ai-scrum-copilot-mvp"


def log_extraction_run(meeting_id: str, run_id: str, transcript: str, result) -> None:
    mlflow = _get_configured_mlflow()
    if mlflow is None:
        return

    try:
        with mlflow.start_run(run_name=run_id):
            mlflow.log_param("meeting_id", meeting_id)
            mlflow.log_param("transcript_chars", len(transcript))
            mlflow.log_param("tasks_count", len(result.tasks))
            mlflow.log_text(transcript, "artifacts/transcript.txt")
            mlflow.log_text(json.dumps(result.dict(), ensure_ascii=False, indent=2), "artifacts/extraction.json")
    except Exception as exc:  # pragma: no cover - safety net to keep API responsive
        logger.exception("Failed to log extraction run to MLflow: %s", exc)


@lru_cache(maxsize=1)
def _get_configured_mlflow():
    try:
        import mlflow
    except Exception as exc:
        logger.warning("MLflow is not available: %s", exc)
        return None

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    token = os.getenv("MLFLOW_API_TOKEN")
    if token:
        os.environ["MLFLOW_TRACKING_TOKEN"] = token

    experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", DEFAULT_EXPERIMENT_NAME)
    try:
        mlflow.set_experiment(experiment_name)
    except Exception as exc:
        logger.error("Unable to set MLflow experiment '%s': %s", experiment_name, exc)
        return None

    return mlflow
