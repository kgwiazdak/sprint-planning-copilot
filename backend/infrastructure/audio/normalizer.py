from __future__ import annotations

import io
import shutil
import subprocess
import wave
from typing import Iterable, List, Tuple


class FFmpegNotAvailableError(RuntimeError):
    """Raised when ffmpeg is missing from PATH."""


def convert_to_standard_wav(content: bytes, *, sample_rate: int, channels: int) -> bytes:
    """Normalize arbitrary audio bytes into mono WAV for Azure."""

    if shutil.which("ffmpeg") is None:
        raise FFmpegNotAvailableError("FFmpeg is required to handle audio but was not found in PATH")

    process = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            "pipe:0",
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
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
        raise RuntimeError(f"Failed to normalize audio via FFmpeg: {error_details}")
    return process.stdout


def wav_payload(wav_bytes: bytes) -> Tuple[bytes, int, int, int, int]:
    with wave.open(io.BytesIO(wav_bytes)) as wav_reader:
        reported_frames = wav_reader.getnframes()
        frames = wav_reader.readframes(reported_frames)
        sample_rate = wav_reader.getframerate()
        sample_width = wav_reader.getsampwidth()
        channels = wav_reader.getnchannels()
    bytes_per_frame = sample_width * channels
    num_frames = len(frames) // bytes_per_frame if bytes_per_frame else 0
    return frames, num_frames, sample_rate, sample_width, channels


def frames_to_ticks(frame_index: int, sample_rate: int) -> int:
    seconds = frame_index / sample_rate
    return int(seconds * 10_000_000)


def build_wav(frames_sequence: Iterable[bytes], sample_rate: int, sample_width: int, channels: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_writer:
        wav_writer.setnchannels(channels)
        wav_writer.setsampwidth(sample_width)
        wav_writer.setframerate(sample_rate)
        for chunk in frames_sequence:
            wav_writer.writeframes(chunk)
    buffer.seek(0)
    return buffer.read()
