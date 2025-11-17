from __future__ import annotations

import logging
import os
from pathlib import Path
from functools import lru_cache

from backend.application.services.voice_profiles import VoiceSamplesSyncService, register_voice_samples
from backend.application.use_cases.extract_meeting import ExtractMeetingUseCase
from backend.infrastructure.jira import JiraClient
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
    SUPPORTED_AUDIO_EXTENSIONS,
)
from backend.settings import get_settings

logger = logging.getLogger(__name__)


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
def get_transcriber() -> AzureConversationTranscriber | None:
    cfg = get_settings().azure_speech
    if not cfg.key or not cfg.region:
        return None
    intro_dir = _ensure_intro_samples_dir()
    if get_settings().mock_audio.enabled:
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
    )


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
    return ExtractMeetingUseCase(
        blob_storage=blob,
        transcription=transcription,
        extractor=extractor,
        meetings_repo=repo,
        telemetry=telemetry,
        audio_extensions=SUPPORTED_AUDIO_EXTENSIONS,
    )


@lru_cache(maxsize=1)
def get_meeting_queue():
    settings = get_settings()
    queue_cfg = getattr(settings, "queue", None)
    connection_string = None
    queue_name = None
    if queue_cfg:
        connection_string = queue_cfg.connection_string or settings.blob_storage.connection_string
        queue_name = queue_cfg.queue_name
    if connection_string and queue_name:
        return AzureMeetingImportQueue(
            connection_string=connection_string,
            queue_name=queue_name,
        )
    logger.warning("Azure queue configuration missing; falling back to in-process queue")
    use_case = get_extract_use_case()
    return BackgroundMeetingImportQueue(use_case.process_job)


@lru_cache(maxsize=1)
def get_meeting_queue_worker() -> AzureQueueWorker | None:
    settings = get_settings()
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
def get_jira_client() -> JiraClient | None:
    cfg = get_settings().jira
    if not cfg.base_url or not cfg.email or not cfg.api_token or not cfg.project_key:
        return None
    try:
        return JiraClient(
            base_url=cfg.base_url,
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
    if not cfg.connection_string or not cfg.container_workers_name:
        return target
    try:
        syncer = VoiceSamplesSyncService(
            connection_string=cfg.connection_string,
            container_name=cfg.container_workers_name,
            target_dir=target,
        )
        samples = syncer.sync()
        if samples:
            register_voice_samples(get_meetings_repository(), samples)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to synchronize intro samples: %s", exc)
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
