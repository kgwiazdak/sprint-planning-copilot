import asyncio
import os
import pathlib
import uuid
from azure.core.exceptions import AzureError, ResourceExistsError
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, ContentSettings, generate_blob_sas
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.mlflow_logging import logger


class BlobStorageConfigError(RuntimeError):
    """Raised when Azure Blob Storage is not configured correctly."""


class BlobStorageUploadError(RuntimeError):
    """Raised when uploading a blob fails."""


@dataclass(frozen=True)
class BlobUploadToken:
    blob_url: str
    upload_url: str
    expires_at: datetime
    blob_path: str


class BlobStorageService:
    """Uploads files to an Azure Blob Storage container."""

    def __init__(
            self,
            *,
            container_name: str,
            connection_string: Optional[str] = None,
    ):
        if not container_name or not connection_string:
            raise BlobStorageConfigError(
                "AZURE_STORAGE_CONTAINER_NAME and AZURE_STORAGE_CONNECTION_STRING are required.")

        service_client = BlobServiceClient.from_connection_string(connection_string)
        self._container_name = container_name
        self._container_client = service_client.get_container_client(container_name)
        self._account_name = service_client.account_name
        parts = self._parse_connection_string(connection_string)
        self._account_key = parts.get("AccountKey")
        self._ensure_container_exists()
        self._max_upload_ttl_seconds = max(60, min(int(os.getenv("BLOB_UPLOAD_MAX_TTL_SECONDS", "900")), 3600))

    @classmethod
    def from_env(cls) -> "BlobStorageService":
        container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME")
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

        if connection_string:
            return cls(container_name=container_name, connection_string=connection_string)

        raise BlobStorageConfigError(
            "Azure Blob Storage is not configured. Set AZURE_STORAGE_CONTAINER_NAME and authentication variables."
        )

    def _ensure_container_exists(self) -> None:
        try:
            self._container_client.create_container()
            logger.info("Created Azure Blob container '%s'", self._container_name)
        except ResourceExistsError:
            # Container already exists, which is fine.
            pass
        except AzureError as exc:
            raise BlobStorageConfigError(
                f"Unable to access Azure Blob container '{self._container_name}'. Check credentials and permissions."
            ) from exc

    async def save_file(
            self,
            *,
            meeting_id: str,
            original_filename: str,
            content: bytes,
            content_type: Optional[str],
    ) -> str:
        blob_name = self._build_blob_name(meeting_id, original_filename)
        blob_url = await asyncio.to_thread(self._upload_bytes, blob_name, content, content_type)
        return blob_url

    async def upload_blob(
            self,
            *,
            blob_name: str,
            content: bytes,
            content_type: Optional[str],
    ) -> str:
        return await asyncio.to_thread(self._upload_bytes, blob_name, content, content_type)

    def _upload_bytes(self, blob_name: str, data: bytes, content_type: Optional[str]) -> str:
        blob_client = self._container_client.get_blob_client(blob=blob_name)
        try:
            blob_client.upload_blob(
                data,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type or "application/octet-stream"),
            )
            logger.info("Uploaded file to Azure Blob Storage: %s", blob_name)
        except AzureError as exc:
            raise BlobStorageUploadError(f"Uploading blob '{blob_name}' failed") from exc
        return blob_client.url

    def generate_upload_token(
            self,
            *,
            meeting_id: str,
            original_filename: str,
            content_type: Optional[str],
            expires_in_seconds: int = 3600,
    ) -> BlobUploadToken:
        if not self._account_key:
            raise BlobStorageConfigError("Azure Storage account key is required to generate SAS upload URLs.")
        blob_name = self._build_blob_name(meeting_id, original_filename)
        ttl = self.clamp_token_ttl(
            expires_in_seconds,
            max_seconds=self._max_upload_ttl_seconds,
        )
        expiry = datetime.now(tz=timezone.utc) + timedelta(seconds=ttl)
        sas = generate_blob_sas(
            account_name=self._account_name,
            container_name=self._container_name,
            blob_name=blob_name,
            account_key=self._account_key,
            permission=BlobSasPermissions(write=True, create=True),
            expiry=expiry,
            content_type=content_type,
        )
        base_url = f"{self._container_client.url}/{blob_name}"
        upload_url = f"{base_url}?{sas}"
        return BlobUploadToken(
            blob_url=base_url,
            upload_url=upload_url,
            expires_at=expiry,
            blob_path=blob_name,
        )

    async def download_blob(self, blob_url: str) -> bytes:
        blob_name = self._extract_blob_name(blob_url)
        return await asyncio.to_thread(self._download_bytes, blob_name)

    def download_blob_by_name_sync(self, blob_name: str) -> bytes:
        return self._download_bytes(blob_name)

    def _download_bytes(self, blob_name: str) -> bytes:
        blob_client = self._container_client.get_blob_client(blob=blob_name)
        try:
            stream = blob_client.download_blob(max_concurrency=4)
            return stream.readall()
        except AzureError as exc:
            raise BlobStorageUploadError(f"Downloading blob '{blob_name}' failed") from exc

    @staticmethod
    def _build_blob_name(meeting_id: str, original_filename: str) -> str:
        safe_name = pathlib.Path(original_filename or "uploaded_file").name.replace(" ", "_")
        suffix = safe_name or f"file-{uuid.uuid4()}"
        return f"{meeting_id}/{suffix}"

    def _extract_blob_name(self, blob_url: str) -> str:
        prefix = f"{self._container_client.url}/"
        if not blob_url.startswith(prefix):
            raise BlobStorageUploadError("Blob URL does not belong to configured container.")
        return blob_url[len(prefix):]

    @staticmethod
    def _parse_connection_string(connection_string: str) -> dict[str, str]:
        parts: dict[str, str] = {}
        for segment in connection_string.split(";"):
            if not segment or "=" not in segment:
                continue
            key, value = segment.split("=", 1)
            parts[key] = value
        return parts

    @staticmethod
    def clamp_token_ttl(requested: Optional[int], *, max_seconds: int, min_seconds: int = 60) -> int:
        if not requested or requested <= 0:
            return max_seconds
        return max(min_seconds, min(requested, max_seconds))
