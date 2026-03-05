from __future__ import annotations

import asyncio
import pathlib
from typing import Optional


class LocalStorageError(RuntimeError):
    """Raised when local file storage operations fail."""


class LocalFileStorageService:
    """Stores upload payloads on local disk and addresses them via local:// URIs."""

    def __init__(self, *, root_dir: str) -> None:
        self._root = pathlib.Path(root_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    async def save_file(
            self,
            *,
            meeting_id: str,
            original_filename: str,
            content: bytes,
            content_type: Optional[str],
    ) -> str:
        del content_type
        safe_name = self._sanitize_filename(original_filename or "uploaded_file")
        rel = f"{meeting_id}/{safe_name}"
        return await self.upload_blob(blob_name=rel, content=content, content_type=None)

    async def upload_blob(
            self,
            *,
            blob_name: str,
            content: bytes,
            content_type: Optional[str],
    ) -> str:
        del content_type
        rel_path = self._sanitize_relative_path(blob_name)
        full_path = self._root / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(full_path.write_bytes, content)
        return self.build_blob_url(rel_path)

    async def download_blob(self, blob_url: str) -> bytes:
        rel = self._extract_relative_path(blob_url, strict_uri=True)
        path = self._root / rel
        if not path.exists():
            raise LocalStorageError(f"Local blob '{blob_url}' was not found.")
        return await asyncio.to_thread(path.read_bytes)

    def download_blob_by_name_sync(self, blob_name: str) -> bytes:
        rel = self._extract_relative_path(blob_name, strict_uri=False)
        path = self._root / rel
        if not path.exists():
            raise LocalStorageError(f"Local blob '{blob_name}' was not found.")
        return path.read_bytes()

    def build_blob_url(self, blob_name: str) -> str:
        rel = self._sanitize_relative_path(blob_name)
        normalized = rel.replace("\\", "/")
        return f"local://{normalized}"

    async def delete_blob(self, blob_url: str) -> bool:
        rel = self._extract_relative_path(blob_url, strict_uri=True)
        path = self._root / rel
        if not path.exists():
            return False
        await asyncio.to_thread(path.unlink)
        return True

    def _extract_relative_path(self, blob_url: str, *, strict_uri: bool) -> str:
        if blob_url.startswith("local://"):
            raw = blob_url[len("local://"):]
            return self._sanitize_relative_path(raw)
        if strict_uri:
            raise LocalStorageError("Local blob URL must use the local:// scheme.")
        return self._sanitize_relative_path(blob_url)

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        base = pathlib.Path(filename).name.replace(" ", "_")
        return base or "uploaded_file"

    @staticmethod
    def _sanitize_relative_path(path: str) -> str:
        candidate = path.replace("\\", "/").lstrip("/")
        normalized = pathlib.PurePosixPath(candidate)
        if any(part in {"", ".", ".."} for part in normalized.parts):
            raise LocalStorageError("Invalid local blob path.")
        return str(normalized)
