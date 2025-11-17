"""Backward-compatible entrypoints for speech-to-text functionality."""

from __future__ import annotations

from backend.settings import get_config
from backend.infrastructure.transcription.azure_conversation import (
    AzureConversationTranscriber,
    SUPPORTED_AUDIO_EXTENSIONS,
)


def _default_transcriber() -> AzureConversationTranscriber:
    cfg = get_config()
    return AzureConversationTranscriber(
        key=cfg.azure_speech.key,
        region=cfg.azure_speech.region,
        language=cfg.azure_speech.language,
        sample_rate=cfg.azure_speech.sample_rate,
    )


def transcribe_audio_if_needed(content: bytes, filename: str) -> str:
    transcriber = _default_transcriber()
    return transcriber.transcribe(content, filename)


__all__ = [
    "AzureConversationTranscriber",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "transcribe_audio_if_needed",
]
