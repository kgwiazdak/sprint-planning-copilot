"""Speech-to-text utilities backed by OpenAI Whisper."""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from typing import Tuple

import whisper

_DEFAULT_MODEL_NAME = os.getenv("WHISPER_MODEL", "small")
SUPPORTED_AUDIO_EXTENSIONS: Tuple[str, ...] = (
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
    ".webm",
    ".mp4",
)


@lru_cache(maxsize=1)
def _load_model(model_name: str) -> whisper.Whisper:
    """Load a Whisper model once per process."""

    return whisper.load_model(model_name)


def _transcribe_file(path: str, model_name: str) -> str:
    model = _load_model(model_name)
    result = model.transcribe(path)
    return result.get("text", "").strip()


def transcribe_audio_if_needed(content: bytes, filename: str) -> str:
    """Transcribe supported audio files using Whisper."""

    extension = os.path.splitext(filename)[1].lower()
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        raise ValueError(f"Unsupported audio format: {extension}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
        tmp_file.write(content)
        tmp_path = tmp_file.name

    try:
        return _transcribe_file(tmp_path, _DEFAULT_MODEL_NAME)
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
