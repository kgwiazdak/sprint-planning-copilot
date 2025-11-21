from __future__ import annotations

import logging
from azure.core.exceptions import AzureError
from azure.storage.blob import BlobServiceClient
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from backend.domain.ports import MeetingsRepositoryPort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceSample:
    display_name: str
    blob_name: str
    local_path: Path


class VoiceSamplesSyncService:
    """Downloads intro_* voice samples from a dedicated Azure container."""

    def __init__(
            self,
            *,
            connection_string: str,
            container_name: str,
            target_dir: Path,
    ) -> None:
        self._target_dir = target_dir
        self._service = BlobServiceClient.from_connection_string(connection_string)
        self._container = self._service.get_container_client(container_name)

    def sync(self) -> list[VoiceSample]:
        samples: list[VoiceSample] = []
        self._target_dir.mkdir(parents=True, exist_ok=True)
        try:
            blobs = self._container.list_blobs(name_starts_with="intro_")
        except AzureError as exc:
            logger.warning("Failed to enumerate intro samples: %s", exc)
            return samples

        for blob in blobs:
            name = blob.name
            display_name = self._display_name_from_blob(name)
            if not display_name:
                continue
            local_path = self._target_dir / Path(name).name
            if not local_path.exists():
                try:
                    logger.info("Downloading intro sample %s -> %s", name, local_path)
                    self._download_blob(name, local_path)
                except AzureError as exc:
                    logger.warning("Failed to download %s: %s", name, exc)
                    continue
            samples.append(VoiceSample(display_name=display_name, blob_name=name, local_path=local_path))
        return samples

    def _download_blob(self, blob_name: str, destination: Path) -> None:
        blob_client = self._container.get_blob_client(blob_name)
        data = blob_client.download_blob(max_concurrency=2).readall()
        destination.write_bytes(data)

    @staticmethod
    def _display_name_from_blob(blob_name: str) -> str | None:
        stem = Path(blob_name).stem
        normalized = stem
        if normalized.lower().startswith("intro_"):
            normalized = normalized[6:]
        normalized = normalized.replace("_", " ").strip()
        if not normalized:
            return None

        def _title_token(token: str) -> str:
            if "-" not in token:
                return token.capitalize()
            return "-".join(part.capitalize() for part in token.split("-") if part)

        parts = [_title_token(token) for token in normalized.split() if token]
        return " ".join(parts) if parts else None


def register_voice_samples(repo: MeetingsRepositoryPort, samples: Iterable[VoiceSample]) -> None:
    """Ensure every downloaded voice sample has a matching user row."""
    for sample in samples:
        repo.register_voice_profile(display_name=sample.display_name, voice_sample_path=str(sample.local_path))
