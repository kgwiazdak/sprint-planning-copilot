"""Speech-to-text utilities backed by Azure Speech Services."""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from typing import Tuple

import azure.cognitiveservices.speech as speechsdk

SUPPORTED_AUDIO_EXTENSIONS: Tuple[str, ...] = (
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
    ".webm",
    ".mp4",
)


class SpeechConfigurationError(RuntimeError):
    """Raised when Azure Speech configuration is missing or invalid."""


@lru_cache(maxsize=1)
def _speech_config() -> speechsdk.SpeechConfig:
    """Create a cached Azure Speech configuration instance."""

    key = os.getenv("AZURE_SPEECH_KEY")
    region = os.getenv("AZURE_SPEECH_REGION")
    if not key or not region:
        raise SpeechConfigurationError("Azure Speech key and region must be configured")

    config = speechsdk.SpeechConfig(subscription=key, region=region)
    language = os.getenv("AZURE_SPEECH_LANGUAGE", "en-US")
    config.speech_recognition_language = language
    return config


def _transcribe_file(path: str) -> str:
    config = _speech_config()
    audio_config = speechsdk.AudioConfig(filename=path)
    recognizer = speechsdk.SpeechRecognizer(speech_config=config, audio_config=audio_config)
    result = recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        return result.text.strip()
    if result.reason == speechsdk.ResultReason.NoMatch:
        raise RuntimeError("No speech could be recognized.")

    cancellation_details = result.cancellation_details
    error_details = getattr(cancellation_details, "error_details", "")
    message = f"Speech recognition canceled: {cancellation_details.reason}"
    if error_details:
        message = f"{message}. {error_details}"
    raise RuntimeError(message)


def transcribe_audio_if_needed(content: bytes, filename: str) -> str:
    """Transcribe supported audio files using Azure Speech Services."""

    extension = os.path.splitext(filename)[1].lower()
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        raise ValueError(f"Unsupported audio format: {extension}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
        tmp_file.write(content)
        tmp_path = tmp_file.name

    try:
        return _transcribe_file(tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
