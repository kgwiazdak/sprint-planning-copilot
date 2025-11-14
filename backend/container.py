from __future__ import annotations

from functools import lru_cache

from backend.application.use_cases.extract_meeting import ExtractMeetingUseCase
from backend.infrastructure.llm.task_extractor import LLMExtractor
from backend.infrastructure.persistence.sqlite import SqliteMeetingsRepository
from backend.infrastructure.storage.blob import BlobStorageService
from backend.infrastructure.telemetry.mlflow_adapter import MLflowTelemetryAdapter
from backend.infrastructure.transcription.azure_conversation import (
    AzureConversationTranscriber,
    SUPPORTED_AUDIO_EXTENSIONS,
)
from backend.settings import get_settings


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
def get_transcriber() -> AzureConversationTranscriber | None:
    cfg = get_settings().azure_speech
    if not cfg.key or not cfg.region:
        return None
    return AzureConversationTranscriber(
        key=cfg.key,
        region=cfg.region,
        language=cfg.language,
        sample_rate=cfg.sample_rate,
    )


@lru_cache(maxsize=1)
def get_meetings_repository() -> SqliteMeetingsRepository:
    cfg = get_settings().database
    return SqliteMeetingsRepository(cfg.url)


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
