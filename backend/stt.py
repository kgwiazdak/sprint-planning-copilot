"""Speech-to-text utilities backed by Azure Speech Services."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import threading
import wave
from functools import lru_cache
from typing import List, Tuple

import azure.cognitiveservices.speech as speechsdk

SUPPORTED_AUDIO_EXTENSIONS: Tuple[str, ...] = (".wav", ".mp3")


class Transcriber:
    def __init__(self) -> None:
        self.SUPPORTED_AUDIO_EXTENSIONS: Tuple[str, ...] = SUPPORTED_AUDIO_EXTENSIONS

    @lru_cache(maxsize=1)
    def _speech_config(self) -> speechsdk.SpeechConfig:
        """Create a cached Azure Speech configuration instance."""

        key = os.getenv("AZURE_SPEECH_KEY")
        region = os.getenv("AZURE_SPEECH_REGION")

        assert key and region, "Azure Speech key and region must be configured"
        config = speechsdk.SpeechConfig(subscription=key, region=region)

        language = os.getenv("AZURE_SPEECH_LANGUAGE", "en-US")
        config.speech_recognition_language = language
        return config

    @staticmethod
    def _audio_config_from_bytes(content: bytes, extension: str) -> speechsdk.audio.AudioConfig:
        """Create an audio config for Azure Speech from in-memory audio content."""

        content = Transcriber._ensure_wav_content(content, extension)

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

    @staticmethod
    def _ensure_wav_content(content: bytes, extension: str) -> bytes:
        """Return WAV bytes, converting from other supported formats if needed."""

        if extension == ".wav":
            return content
        if extension != ".mp3":
            raise ValueError(
                f"Unsupported audio format: {extension}. Only WAV or MP3 are supported"
            )
        if shutil.which("ffmpeg") is None:
            raise ValueError("FFmpeg is required to handle MP3 audio but was not found in PATH")

        process = subprocess.run(
            [
                "ffmpeg",
                "-i",
                "pipe:0",
                "-f",
                "wav",
                "-acodec",
                "pcm_s16le",
                "pipe:1",
            ],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.returncode != 0:
            error_details = process.stderr.decode("utf-8", errors="ignore").strip()
            raise ValueError(f"Failed to decode MP3 audio via FFmpeg: {error_details}")
        return process.stdout

    def transcribe_content(self, content: bytes, extension: str) -> str:
        config = self._speech_config()
        audio_config = self._audio_config_from_bytes(content, extension)
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
    assert extension in SUPPORTED_AUDIO_EXTENSIONS, f"Unsupported audio format: {extension}"
    transcriber = Transcriber()
    return transcriber.transcribe_content(content, extension)
