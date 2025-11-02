"""Speech-to-text utilities backed by Azure Speech Services."""

from __future__ import annotations

import os
import threading
from functools import lru_cache
from typing import List, Tuple

import azure.cognitiveservices.speech as speechsdk
from backend.logger import logger

SUPPORTED_AUDIO_EXTENSIONS: Tuple[str, ...] = (".wav",)


class SpeechConfigurationError(RuntimeError):
    """Raised when Azure Speech configuration is missing or invalid."""


@lru_cache(maxsize=1)
def _speech_config() -> speechsdk.SpeechConfig:
    """Create a cached Azure Speech configuration instance."""

    key = os.getenv("AZURE_SPEECH_KEY")
    region = os.getenv("AZURE_SPEECH_REGION")

    if not key:
        raise SpeechConfigurationError("Azure Speech key must be configured")
    if region:
        config = speechsdk.SpeechConfig(subscription=key, region=region)
    else:
        raise SpeechConfigurationError(
            "Azure Speech Key or region must be configured"
        )

    language = os.getenv("AZURE_SPEECH_LANGUAGE", "en-US")
    config.speech_recognition_language = language
    return config


def _audio_config_from_bytes(content: bytes, extension: str) -> speechsdk.audio.AudioConfig:
    """Create an audio config for Azure Speech from in-memory audio content."""

    import io
    import wave

    if extension != ".wav":
        raise ValueError(
            f"Unsupported audio format: {extension}. Only uncompressed WAV is supported"
        )

    try:
        with wave.open(io.BytesIO(content)) as wav_reader:
            frames = wav_reader.readframes(wav_reader.getnframes())
            sample_rate = wav_reader.getframerate()
            bits_per_sample = wav_reader.getsampwidth() * 8
            channels = wav_reader.getnchannels()
    except wave.Error as exc:  # pragma: no cover - depends on input data
        raise ValueError("Unable to read WAV audio data") from exc

    stream_format = speechsdk.audio.AudioStreamFormat(
        sample_rate,
        bits_per_sample,
        channels,
    )
    stream = speechsdk.audio.PushAudioInputStream(stream_format=stream_format)
    stream.write(frames)
    stream.close()
    return speechsdk.audio.AudioConfig(stream=stream)


def _transcribe_content(content: bytes, extension: str) -> str:
    config = _speech_config()
    audio_config = _audio_config_from_bytes(content, extension)
    recognizer = speechsdk.SpeechRecognizer(speech_config=config, audio_config=audio_config)

    recognized_segments: List[str] = []
    done = threading.Event()
    canceled_error: List[str] = []

    def _recognized_handler(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        result = evt.result
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = result.text.strip()
            if text:
                recognized_segments.append(text)

    def _canceled_handler(evt: speechsdk.SpeechRecognitionCanceledEventArgs) -> None:
        cancellation_details = evt.result.cancellation_details
        if cancellation_details.reason == speechsdk.CancellationReason.EndOfStream:
            done.set()
            return

        error_details = getattr(cancellation_details, "error_details", "")
        message = f"Speech recognition canceled: {cancellation_details.reason}"
        if error_details:
            message = f"{message}. {error_details}"
        canceled_error.append(message)
        done.set()

    def _stopped_handler(_: speechsdk.SessionEventArgs) -> None:
        done.set()

    recognizer.recognized.connect(_recognized_handler)
    recognizer.canceled.connect(_canceled_handler)
    recognizer.session_stopped.connect(_stopped_handler)

    started = False
    try:
        recognizer.start_continuous_recognition_async().get()
        started = True
        done.wait(timeout=60)
    finally:
        try:
            if started:
                recognizer.stop_continuous_recognition_async().get()
        finally:
            recognizer.recognized.disconnect_all()

    if canceled_error:
        raise RuntimeError(canceled_error[0])
    if not recognized_segments:
        raise RuntimeError("No speech could be recognized.")

    return " ".join(recognized_segments)

def transcribe_audio_if_needed(content: bytes, filename: str) -> str:
    """Transcribe supported audio files using Azure Speech Services."""

    extension = os.path.splitext(filename)[1].lower()
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        raise ValueError(f"Unsupported audio format: {extension}")

    return _transcribe_content(content, extension)
