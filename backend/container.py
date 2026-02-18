from __future__ import annotations

import fnmatch
import logging
import os
from functools import lru_cache
from pathlib import Path

from backend.application.services.voice_profiles import VoiceSamplesSyncService
from backend.application.use_cases.extract_meeting import ExtractMeetingUseCase
from backend.application.services.rag_estimator import RAGEstimator
from backend.domain.ports import TranscriptionPort
from backend.infrastructure.jira import JiraClient
from backend.infrastructure.mcp import MCPAtlassianClient
from backend.infrastructure.llm.task_extractor import LLMExtractor
from backend.infrastructure.persistence.cosmos import CosmosMeetingsRepository
from backend.infrastructure.persistence.sqlite import SqliteMeetingsRepository
from backend.infrastructure.queue.azure_storage import (
    AzureMeetingImportQueue,
    AzureQueueWorker,
    _ensure_queue_client,
)
from backend.infrastructure.queue.background import BackgroundMeetingImportQueue
from backend.infrastructure.storage.blob import BlobStorageService
from backend.infrastructure.telemetry.mlflow_adapter import MLflowTelemetryAdapter
from backend.infrastructure.transcription.azure_conversation import (
    AzureConversationTranscriber,
    IntroClip,
    SUPPORTED_AUDIO_EXTENSIONS,
)
from backend.settings import get_settings

logger = logging.getLogger(__name__)


class MockTranscriber(TranscriptionPort):
    """Lightweight transcriber used when MOCK_TRANSCRIBER is enabled."""

    SUPPORTED_AUDIO_EXTENSIONS: tuple[str, ...] = (
        ".wav",
        ".mp3",
        ".m4a",
        ".aac",
        ".wma",
        ".ogg",
        ".flac",
    )

    def __init__(self, transcript: str | None = None) -> None:
        default = _default_mock_transcript()
        self._transcript = transcript.strip() if transcript else default

    def set_owner(self, owner_id: str | None) -> None:
        return None

    def transcribe(self, content: bytes, filename: str) -> str:
        return self._transcript


def _default_mock_transcript() -> str:
    """Deterministic transcript matching the bundled mock audio storyline."""
    return "\n".join(
        [
            "Adrian Puchacki: Morning team, let's keep this simple. We need four tasks and clear owners.",
            "Waldemar Walasik: Morning. Training still takes four hours on Azure, even after the ingest refactor.",
            "Wojciech Puczyk: I can parallelize preprocessing with Dask. Nice and clear: that would be my task.",
            "Adrian Puchacki: Great, Wojciech owns Dask parallelization. How many points would that be?",
            "Wojciech Puczyk: Let's vote it at 5 points. It's mostly wiring and testing.",
            "Adrian Puchacki: Done. Task one: Wojciech, Dask parallelization, 5 points.",
            "Waldemar Walasik: After that, I will update the model registry and redeploy via MLflow. That's my task.",
            "Adrian Puchacki: How many points do you want for the registry and redeploy, Waldemar?",
            "Waldemar Walasik: Call it 3 points. Small changes and smoke tests.",
            "Adrian Puchacki: Good. Task two: Waldemar, registry update plus redeploy, 3 points.",
            "Adrian Puchacki: We also need drift detection and alerting. Waldemar, do you want that too?",
            "Waldemar Walasik: Yes, I'll take drift alerts. Simple rule: alert if accuracy drops more than three percent.",
            "Adrian Puchacki: Points for drift alerting?",
            "Waldemar Walasik: 3 points is fine, includes Slack notification and MLflow log.",
            "Adrian Puchacki: Task three: Waldemar, drift detection and alerting, 3 points.",
            "Wojciech Puczyk: Do we need a release brief for stakeholders?",
            "Adrian Puchacki: Yes, I'll own the release-readiness checklist and brief. Very small.",
            "Waldemar Walasik: How many points for your brief, Adrian?",
            "Adrian Puchacki: 1 point. Just making sure it's tracked.",
            "Adrian Puchacki: Task four: Adrian, release brief and checklist, 1 point.",
            "Wojciech Puczyk: Recap so we don't mess it up: I own Dask parallelization, 5 points.",
            "Waldemar Walasik: I own registry plus redeploy for 3 points, and drift alerting for 3 points.",
            "Adrian Puchacki: And I own the release brief at 1 point. Four tasks total, owners clear.",
            "Wojciech Puczyk: Timeline: finish by Thursday, quick demo Friday. Let's keep it simple.",
            "Waldemar Walasik: No extra tasks hiding here. Just these four.",
            "Adrian Puchacki: Perfect. Thanks—execute and update the board.",
        ]
    )


@lru_cache(maxsize=1)
def get_blob_storage() -> BlobStorageService | None:
    cfg = get_settings().blob_storage
    if not cfg.container_name or not cfg.connection_string:
        return None
    return BlobStorageService(
        container_name=cfg.container_name,
        connection_string=cfg.connection_string,
    )


@lru_cache(maxsize=1)
def get_worker_blob_storage() -> BlobStorageService | None:
    cfg = get_settings().blob_storage
    if not cfg.container_workers_name or not cfg.connection_string:
        return None
    return BlobStorageService(
        container_name=cfg.container_workers_name,
        connection_string=cfg.connection_string,
    )


@lru_cache(maxsize=1)
def get_transcriber() -> TranscriptionPort | None:
    settings = get_settings()
    mock_flag = os.getenv("MOCK_TRANSCRIBER", "").lower() in {"1", "true", "yes", "on"}
    prefer_mock_audio = settings.mock_audio.enabled and os.getenv(
        "MOCK_TRANSCRIBER_FOR_MOCK_AUDIO", "true"
    ).lower() in {"1", "true", "yes", "on"}
    if mock_flag or prefer_mock_audio:
        return MockTranscriber(os.getenv("MOCK_TRANSCRIPT_TEXT"))
    cfg = settings.azure_speech
    if not cfg.key or not cfg.region:
        return None
    intro_dir = _ensure_intro_samples_dir()
    intro_loader = _build_intro_loader()
    if settings.mock_audio.enabled:
        try:
            get_mock_audio_path()
        except Exception:  # pragma: no cover - defensive
            logger.debug("Mock audio ensure failed during transcriber init.", exc_info=True)
    return AzureConversationTranscriber(
        key=cfg.key,
        region=cfg.region,
        language=cfg.language,
        sample_rate=cfg.sample_rate,
        intro_audio_dir=intro_dir,
        intro_loader=intro_loader,
    )


def _build_intro_loader():
    storage = get_worker_blob_storage()
    repo = get_meetings_repository()
    if not storage:
        return None
    pattern = os.getenv("INTRO_AUDIO_PATTERN", "intro_*.*")
    prefix = pattern.split("*", 1)[0]
    container_prefix = f"{storage._container_client.url}/"

    def _blob_name(path: str) -> str | None:
        if not path:
            return None
        if path.startswith(container_prefix):
            return path[len(container_prefix):].split("?", 1)[0]
        if "://" not in path:
            return path
        return None

    def _load(owner_id: str | None) -> list[IntroClip]:
        clips: list[IntroClip] = []
        if not owner_id:
            return clips
        try:
            users = repo.list_users(owner_id=owner_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to list users for owner %s: %s", owner_id, exc)
            return clips
        for user in users:
            blob_name = _blob_name(user.get("voiceSamplePath"))
            if not blob_name:
                continue
            filename = Path(blob_name).name
            if not fnmatch.fnmatch(filename, pattern):
                continue
            try:
                payload = storage.download_blob_by_name_sync(blob_name)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to stream intro sample %s: %s", blob_name, exc)
                continue
            role = VoiceSamplesSyncService._display_name_from_blob(filename) or AzureConversationTranscriber._role_from_filename(Path(filename))
            try:
                source_url = storage.build_blob_url(blob_name)
            except Exception:
                source_url = blob_name
            clips.append(IntroClip(role=role, content=payload, source=source_url))
        return clips

    return _load


@lru_cache(maxsize=1)
def get_meetings_repository():
    settings = get_settings()
    db_cfg = settings.database
    cosmos_cfg = settings.cosmos
    use_cosmos = db_cfg.provider == "cosmos" or (cosmos_cfg.account_uri and cosmos_cfg.key)
    if use_cosmos:
        if not cosmos_cfg.account_uri or not cosmos_cfg.key:
            raise RuntimeError("COSMOS_ACCOUNT_URI and COSMOS_KEY must be set when DB_PROVIDER=cosmos.")
        return CosmosMeetingsRepository(
            account_uri=cosmos_cfg.account_uri,
            key=cosmos_cfg.key,
            database_name=cosmos_cfg.database,
            meetings_container=cosmos_cfg.meetings_container,
            tasks_container=cosmos_cfg.tasks_container,
            users_container=cosmos_cfg.users_container,
            runs_container=cosmos_cfg.runs_container,
        )
    return SqliteMeetingsRepository(db_cfg.url)


@lru_cache(maxsize=1)
def get_telemetry() -> MLflowTelemetryAdapter:
    return MLflowTelemetryAdapter()


@lru_cache(maxsize=1)
def get_extractor() -> LLMExtractor:
    return LLMExtractor()


@lru_cache(maxsize=1)
def get_extract_use_case() -> ExtractMeetingUseCase:
    blob = get_blob_storage()
    transcription = get_transcriber()
    repo = get_meetings_repository()
    telemetry = get_telemetry()
    extractor = get_extractor()
    rag = RAGEstimator()
    return ExtractMeetingUseCase(
        blob_storage=blob,
        transcription=transcription,
        extractor=extractor,
        meetings_repo=repo,
        telemetry=telemetry,
        rag_estimator=rag,
        audio_extensions=SUPPORTED_AUDIO_EXTENSIONS,
    )


@lru_cache(maxsize=1)
def get_meeting_queue():
    settings = get_settings()
    profile = getattr(settings, "profile", "prod")
    # In dev we prefer the in-process background queue unless explicitly forced to Azure.
    azure_queue_forced = os.getenv("ENABLE_AZURE_QUEUE", "").lower() in {"1", "true", "yes", "on"}
    if profile == "dev" and not azure_queue_forced:
        logger.info("Using in-process background queue (dev profile, ENABLE_AZURE_QUEUE not set).")
        use_case = get_extract_use_case()
        return BackgroundMeetingImportQueue(use_case.process_job)
    queue_cfg = getattr(settings, "queue", None)
    connection_string = None
    queue_name = None
    if queue_cfg:
        connection_string = queue_cfg.connection_string or settings.blob_storage.connection_string
        queue_name = queue_cfg.queue_name
    if connection_string and queue_name:
        try:
            return AzureMeetingImportQueue(
                connection_string=connection_string,
                queue_name=queue_name,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Falling back to in-process queue because Azure queue init failed: %s",
                exc,
            )
    else:
        logger.warning("Azure queue configuration missing; falling back to in-process queue")
    use_case = get_extract_use_case()
    return BackgroundMeetingImportQueue(use_case.process_job)


@lru_cache(maxsize=1)
def get_meeting_queue_worker() -> AzureQueueWorker | None:
    settings = get_settings()
    profile = getattr(settings, "profile", "prod")
    azure_queue_forced = os.getenv("ENABLE_AZURE_QUEUE", "").lower() in {"1", "true", "yes", "on"}
    if profile == "dev" and not azure_queue_forced:
        # When using in-process queue in dev, there is no separate worker.
        return None
    queue_cfg = getattr(settings, "queue", None)
    if not queue_cfg:
        return None
    connection_string = queue_cfg.connection_string or settings.blob_storage.connection_string
    queue_name = queue_cfg.queue_name
    if not connection_string or not queue_name:
        return None
    use_case = get_extract_use_case()
    client = _ensure_queue_client(connection_string, queue_name)
    return AzureQueueWorker(
        queue_client=client,
        handler=use_case.process_job,
        visibility_timeout=queue_cfg.visibility_timeout,
        poll_interval_seconds=queue_cfg.poll_interval_seconds,
        max_batch_size=queue_cfg.max_batch_size,
    )


@lru_cache(maxsize=1)
def get_jira_client() -> JiraClient | MCPAtlassianClient | None:
    mcp_cfg = get_settings().mcp
    if mcp_cfg.atlassian_enabled:
        return MCPAtlassianClient(
            server_url=mcp_cfg.atlassian_server_url or "http://localhost:8111/mcp",
            timeout_seconds=mcp_cfg.timeout_seconds,
        )

    cfg = get_settings().jira
    if not cfg.base_url or not cfg.email or not cfg.api_token:
        return None
    try:
        return JiraClient(
            base_url=cfg.base_url,
            browse_base_url=cfg.base_url,
            email=cfg.email,
            api_token=cfg.api_token,
            project_key=cfg.project_key,
            story_points_field=cfg.story_points_field,
        )
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _ensure_intro_samples_dir() -> Path:
    cfg = get_settings().blob_storage
    target = Path(os.getenv("INTRO_AUDIO_DIR", "data/voices"))
    target.mkdir(parents=True, exist_ok=True)
    return target


@lru_cache(maxsize=1)
def get_mock_audio_path() -> Path | None:
    settings = get_settings()
    mock_cfg = settings.mock_audio
    if not mock_cfg.enabled:
        return None
    local_dir = Path(mock_cfg.local_dir or "data")
    local_dir.mkdir(parents=True, exist_ok=True)
    filename = mock_cfg.local_filename or Path(mock_cfg.blob_path).name
    target = local_dir / filename
    if target.exists():
        return target
    storage = get_blob_storage()
    if storage is None:
        logger.warning("Mock audio enabled but blob storage is not configured.")
        return None
    try:
        data = storage.download_blob_by_name_sync(mock_cfg.blob_path)
        target.write_bytes(data)
        logger.info("Downloaded mock audio sample to %s", target)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to download mock audio '%s': %s", mock_cfg.blob_path, exc)
        return None
    return target


if get_settings().mock_audio.enabled:
    try:
        get_mock_audio_path()
    except Exception:  # pragma: no cover - defensive
        logger.debug("Initial mock audio fetch failed.", exc_info=True)
