from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, List

import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech import transcription as speech_transcription

from backend.infrastructure.audio import normalizer


class AzureConversationTranscriber:
    """Azure Cognitive Services backed transcription with intro alignment."""

    SUPPORTED_AUDIO_EXTENSIONS: tuple[str, ...] = (".wav", ".mp3")

    def __init__(
        self,
        *,
        key: str | None,
        region: str | None,
        language: str = "en-US",
        sample_rate: int = 16000,
        channels: int = 1,
        intro_audio_dir: str | Path | None = None,
        intro_pattern: str = "intro_*.mp3",
        intro_silence_ms: int = 300,
    ) -> None:
        if not key or not region:
            raise ValueError("Azure Speech key and region must be configured")

        self._key = key
        self._region = region
        self._language = language
        self._sample_rate = sample_rate
        self._channels = channels
        self._intro_dir = Path(intro_audio_dir or os.getenv("INTRO_AUDIO_DIR", "data"))
        self._intro_pattern = intro_pattern or os.getenv("INTRO_AUDIO_PATTERN", "intro_*.mp3")
        self._intro_silence_ms = intro_silence_ms or int(os.getenv("INTRO_SILENCE_MS", "300"))

        self._speech_config = self._build_speech_config()

    def _build_speech_config(self) -> speechsdk.SpeechConfig:
        config = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
        config.speech_recognition_language = self._language
        return config

    def _audio_config_from_wav(self, wav_bytes: bytes) -> tuple[speechsdk.audio.AudioConfig, Callable[[], None]]:
        frames, _, sample_rate, sample_width, channels = normalizer.wav_payload(wav_bytes)
        stream_format = speechsdk.audio.AudioStreamFormat(
            sample_rate,
            sample_width * 8,
            channels,
        )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format=stream_format)

        def feed_audio() -> None:
            push_stream.write(frames)
            push_stream.close()

        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        return audio_config, feed_audio

    def _load_intro_chunks(self, sample_rate: int, sample_width: int, channels: int):
        if not self._intro_dir.exists():
            return []

        chunks = []
        for path in sorted(self._intro_dir.glob(self._intro_pattern)):
            if not path.is_file():
                continue
            role = path.stem.split("_", 1)[-1].upper()
            wav_bytes = normalizer.convert_to_standard_wav(
                path.read_bytes(), sample_rate=sample_rate, channels=channels
            )
            frames, num_frames, sr, sw, ch = normalizer.wav_payload(wav_bytes)
            if (sr, sw, ch) != (sample_rate, sample_width, channels):
                raise ValueError(f"Intro sample {path.name} has incompatible audio format")
            chunks.append({"role": role, "frames": frames, "num_frames": num_frames})
        return chunks

    def _prepend_reference_intros(
        self,
        meeting_frames: bytes,
        sample_rate: int,
        sample_width: int,
        channels: int,
    ):
        intros = self._load_intro_chunks(sample_rate, sample_width, channels)
        if not intros:
            wav_bytes = normalizer.build_wav([meeting_frames], sample_rate, sample_width, channels)
            return wav_bytes, [], 0

        silence_frames = int(sample_rate * self._intro_silence_ms / 1000)
        silence_chunk = b"\x00" * silence_frames * sample_width * channels if silence_frames else b""

        frames_sequence: List[bytes] = []
        boundaries = []
        frame_cursor = 0

        for intro in intros:
            frames_sequence.append(intro["frames"])
            start_tick = normalizer.frames_to_ticks(frame_cursor, sample_rate)
            frame_cursor += intro["num_frames"]
            end_tick = normalizer.frames_to_ticks(frame_cursor, sample_rate)
            boundaries.append({"role": intro["role"], "start": start_tick, "end": end_tick})
            if silence_chunk:
                frames_sequence.append(silence_chunk)
                frame_cursor += silence_frames

        meeting_start_tick = normalizer.frames_to_ticks(frame_cursor, sample_rate)
        frames_sequence.append(meeting_frames)

        combined_wav = normalizer.build_wav(frames_sequence, sample_rate, sample_width, channels)
        return combined_wav, boundaries, meeting_start_tick

    def transcribe(self, content: bytes, filename: str) -> str:
        if not filename.lower().endswith(self.SUPPORTED_AUDIO_EXTENSIONS):
            raise ValueError(f"Unsupported audio format: {filename}")

        wav_bytes = normalizer.convert_to_standard_wav(
            content, sample_rate=self._sample_rate, channels=self._channels
        )
        meeting_frames, _, sample_rate, sample_width, channels = normalizer.wav_payload(wav_bytes)
        combined_wav, intro_boundaries, meeting_start_tick = self._prepend_reference_intros(
            meeting_frames, sample_rate, sample_width, channels
        )
        audio_config, feed_audio = self._audio_config_from_wav(combined_wav)
        transcriber = speech_transcription.ConversationTranscriber(
            speech_config=self._speech_config,
            audio_config=audio_config,
        )

        recognized_segments: List[str] = []
        done = threading.Event()
        canceled_error: List[str] = []
        speaker_roles: dict = {}

        def _label_for_speaker(speaker_id: int | None) -> str:
            if speaker_id is None:
                return "Speaker"
            return speaker_roles.get(speaker_id, f"Speaker {speaker_id}")

        def _role_for_offset(offset_ticks: int) -> str | None:
            for boundary in intro_boundaries:
                if boundary["start"] <= offset_ticks < boundary["end"]:
                    return boundary["role"]
            return None

        def _recognized_handler(evt: speech_transcription.ConversationTranscriptionEventArgs) -> None:
            result = evt.result
            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                text = result.text.strip()
                if text:
                    offset_ticks = result.offset
                    speaker_id = getattr(result, "speaker_id", None)
                    role = _role_for_offset(offset_ticks)
                    if role and speaker_id is not None:
                        speaker_roles.setdefault(speaker_id, role)
                        return
                    if offset_ticks < meeting_start_tick:
                        return
                    label = _label_for_speaker(speaker_id)
                    recognized_segments.append(f"{label}: {text}")

        def _canceled_handler(evt: speech_transcription.ConversationTranscriptionCanceledEventArgs) -> None:
            cancellation_details = evt.result.cancellation_details
            if cancellation_details.reason == speechsdk.CancellationReason.EndOfStream:
                done.set()
                return

            error_details = getattr(cancellation_details, "error_details", "")
            message = f"Conversation transcription canceled: {cancellation_details.reason}"
            if error_details:
                message = f"{message}. {error_details}"
            canceled_error.append(message)
            done.set()

        def _stopped_handler(_: speechsdk.SessionEventArgs) -> None:
            done.set()

        transcriber.transcribed.connect(_recognized_handler)
        transcriber.canceled.connect(_canceled_handler)
        transcriber.session_stopped.connect(_stopped_handler)

        started = False
        try:
            transcriber.start_transcribing_async().get()
            feed_audio()
            started = True
            done.wait(timeout=60)
        finally:
            try:
                if started:
                    transcriber.stop_transcribing_async().get()
            finally:
                transcriber.transcribed.disconnect_all()

        if canceled_error:
            raise RuntimeError(canceled_error[0])
        if not recognized_segments:
            raise RuntimeError("No speech could be recognized.")

        return "\n".join(recognized_segments)


# Backwards-compatible names for legacy imports
Transcriber = AzureConversationTranscriber
SUPPORTED_AUDIO_EXTENSIONS = AzureConversationTranscriber.SUPPORTED_AUDIO_EXTENSIONS
