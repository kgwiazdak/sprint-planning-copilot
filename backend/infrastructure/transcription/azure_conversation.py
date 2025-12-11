from __future__ import annotations

import azure.cognitiveservices.speech as speechsdk
import logging
import os
import threading
from azure.cognitiveservices.speech import transcription as speech_transcription
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List

from backend.infrastructure.audio import normalizer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntroClip:
    role: str
    content: bytes
    source: str | None = None


class AzureConversationTranscriber:
    """Azure Cognitive Services backed transcription with intro alignment."""

    SUPPORTED_AUDIO_EXTENSIONS: tuple[str, ...] = (".wav", ".mp3")
    DEFAULT_TRANSCRIPTION_TIMEOUT_SECONDS: int = 600
    DEFAULT_STOP_TIMEOUT_SECONDS: int = 10

    def __init__(
            self,
            *,
            key: str | None,
            region: str | None,
            language: str = "en-US",
            sample_rate: int = 16000,
            channels: int = 1,
            intro_audio_dir: str | Path | None = None,
            intro_pattern: str = "intro_*.*",
            intro_silence_ms: int = 300,
            transcription_timeout: int | None = None,
            stop_timeout: int | None = None,
            intro_loader: Callable[[str | None], Iterable[IntroClip]] | None = None,
    ) -> None:
        if not key or not region:
            raise ValueError("Azure Speech key and region must be configured")

        self._key = key
        self._region = region
        self._language = language
        self._sample_rate = sample_rate
        self._channels = channels
        self._intro_dir = Path(intro_audio_dir or os.getenv("INTRO_AUDIO_DIR", "data/voices"))
        self._intro_pattern = intro_pattern or os.getenv("INTRO_AUDIO_PATTERN", "intro_*.*")
        self._intro_silence_ms = intro_silence_ms or int(os.getenv("INTRO_SILENCE_MS", "300"))
        self._transcription_timeout = (
            transcription_timeout
            if transcription_timeout is not None
            else int(os.getenv("TRANSCRIPTION_TIMEOUT_SECONDS", str(self.DEFAULT_TRANSCRIPTION_TIMEOUT_SECONDS)))
        )
        self._stop_timeout = stop_timeout if stop_timeout is not None else int(
            os.getenv("TRANSCRIPTION_STOP_TIMEOUT_SECONDS", str(self.DEFAULT_STOP_TIMEOUT_SECONDS))
        )
        self._intro_loader = intro_loader
        self._current_owner: str | None = None
        self._last_intro_context: dict | None = None

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

    def _load_intro_chunks(self, sample_rate: int, sample_width: int, channels: int, owner_id: str | None):
        clips: list[IntroClip] = []
        if self._intro_loader and owner_id:
            try:
                clips.extend(list(self._intro_loader(owner_id)))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to load intro clips from blob storage: %s", exc)

        if not clips and self._intro_dir.exists():
            for path in sorted(self._intro_dir.glob(self._intro_pattern)):
                if not path.is_file():
                    continue
                try:
                    clips.append(
                        IntroClip(
                            role=self._role_from_filename(path),
                            content=path.read_bytes(),
                            source=str(path),
                        )
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Failed to read intro sample %s: %s", path, exc)

        if not clips:
            self._last_intro_context = {"owner_id": owner_id, "clips": [], "count": 0}
            return []

        normalized = self._normalize_intro_clips(clips, sample_rate, sample_width, channels)
        self._last_intro_context = {
            "owner_id": owner_id,
            "clips": [
                {"role": clip.role, "source": getattr(clip, "source", None)}
                for clip in clips
            ],
            "count": len(normalized),
        }
        return normalized

    def _normalize_intro_clips(
            self,
            clips: Iterable[IntroClip],
            sample_rate: int,
            sample_width: int,
            channels: int,
    ):
        chunks = []
        for clip in clips:
            try:
                wav_bytes = normalizer.convert_to_standard_wav(
                    clip.content, sample_rate=sample_rate, channels=channels
                )
                frames, num_frames, sr, sw, ch = normalizer.wav_payload(wav_bytes)
                if (sr, sw, ch) != (sample_rate, sample_width, channels):
                    raise ValueError(f"Intro sample {clip.role} has incompatible audio format")
                chunks.append({"role": clip.role, "frames": frames, "num_frames": num_frames})
            except Exception as exc:
                logger.warning("Skipping intro clip %s: %s", getattr(clip, "role", "unknown"), exc)
        return chunks

    @staticmethod
    def _role_from_filename(path: Path) -> str:
        stem = path.stem
        if stem.lower().startswith("intro_"):
            stem = stem[6:]
        stem = stem.replace("_", " ").strip()
        if not stem:
            return "Speaker"

        def _title_token(token: str) -> str:
            if "-" not in token:
                return token.capitalize()
            return "-".join(part.capitalize() for part in token.split("-") if part)

        parts = [_title_token(token) for token in stem.split() if token]
        return " ".join(parts) if parts else "Speaker"

    def _prepend_reference_intros(
            self,
            meeting_frames: bytes,
            sample_rate: int,
            sample_width: int,
            channels: int,
    ):
        intros = self._load_intro_chunks(sample_rate, sample_width, channels, self._current_owner)
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

    def set_owner(self, owner_id: str | None) -> None:
        self._current_owner = owner_id
        self._last_intro_context = None

    def get_last_intro_context(self) -> dict | None:
        return self._last_intro_context

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
        timed_out = False
        try:
            transcriber.start_transcribing_async().get()
            feed_audio()
            started = True
            if not done.wait(timeout=self._transcription_timeout):
                timed_out = True
        finally:
            self._cleanup_transcriber(transcriber, started, done)

        if canceled_error:
            raise RuntimeError(canceled_error[0])
        if timed_out:
            raise RuntimeError(
                f"Transcription timed out after {self._transcription_timeout} seconds. "
                "The audio file may be too long or the service is unresponsive."
            )
        if not recognized_segments:
            raise RuntimeError("No speech could be recognized.")

        return "\n".join(recognized_segments)

    def _cleanup_transcriber(
            self,
            transcriber: speech_transcription.ConversationTranscriber,
            started: bool,
            done: threading.Event,
    ) -> None:
        """Safely clean up transcriber resources with timeout protection."""
        try:
            if started:
                stop_future = transcriber.stop_transcribing_async()
                try:
                    stop_future.get(timeout=self._stop_timeout * 1000)
                except Exception:
                    # If stop times out, wait briefly for session_stopped event
                    # then proceed with cleanup regardless
                    done.wait(timeout=1)
        except Exception:
            # Swallow any exceptions during cleanup to prevent masking the original error
            pass
        finally:
            try:
                transcriber.transcribed.disconnect_all()
            except Exception:
                pass
            try:
                transcriber.canceled.disconnect_all()
            except Exception:
                pass
            try:
                transcriber.session_stopped.disconnect_all()
            except Exception:
                pass


# Backwards-compatible names for legacy imports
Transcriber = AzureConversationTranscriber
SUPPORTED_AUDIO_EXTENSIONS = AzureConversationTranscriber.SUPPORTED_AUDIO_EXTENSIONS
