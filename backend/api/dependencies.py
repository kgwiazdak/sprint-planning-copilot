from __future__ import annotations

from functools import lru_cache

from backend.application.workflow import ExtractionWorkflow
from backend.config import get_config
from backend.extractor import LLMExtractor
from backend.infrastructure.persistence.meetings import SQLiteMeetingsRepository
from backend.infrastructure.storage.blob import BlobStorageService
from backend.infrastructure.telemetry.mlflow_adapter import MLflowTelemetryAdapter
from backend.infrastructure.transcription.azure_conversation import (
    AzureConversationTranscriber,
    SUPPORTED_AUDIO_EXTENSIONS,
)


@lru_cache(maxsize=1)
def get_blob_storage_service() -> BlobStorageService | None:
    cfg = get_config().blob_storage
    if not cfg.container_name or not cfg.connection_string:
        return None
    return BlobStorageService(
        container_name=cfg.container_name,
        connection_string=cfg.connection_string,
    )


@lru_cache(maxsize=1)
def get_transcription_service() -> AzureConversationTranscriber | None:
    cfg = get_config().azure_speech
    if not cfg.key or not cfg.region:
        return None
    return AzureConversationTranscriber(
        key=cfg.key,
        region=cfg.region,
        language=cfg.language,
        sample_rate=cfg.sample_rate,
    )


@lru_cache(maxsize=1)
def get_meetings_repository() -> SQLiteMeetingsRepository:
    cfg = get_config().database
    return SQLiteMeetingsRepository(cfg.url)


@lru_cache(maxsize=1)
def get_telemetry_service() -> MLflowTelemetryAdapter:
    return MLflowTelemetryAdapter()


@lru_cache(maxsize=1)
def get_workflow() -> ExtractionWorkflow:
    blob_storage = get_blob_storage_service()
    transcription = get_transcription_service()
    workflow = ExtractionWorkflow(
        blob_storage=blob_storage,
        transcription=transcription,
        extractor=LLMExtractor(),
        meetings_repo=get_meetings_repository(),
        telemetry=get_telemetry_service(),
        audio_extensions=SUPPORTED_AUDIO_EXTENSIONS,
    )
    return workflow
