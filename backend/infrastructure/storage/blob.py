import os
import pathlib
import uuid
from typing import Optional

import anyio
from azure.core.exceptions import AzureError, ResourceExistsError
from azure.storage.blob import BlobServiceClient, ContentSettings

from backend.mlflow_logging import logger


class BlobStorageConfigError(RuntimeError):
    """Raised when Azure Blob Storage is not configured correctly."""


class BlobStorageUploadError(RuntimeError):
    """Raised when uploading a blob fails."""


class BlobStorageService:
    """Uploads files to an Azure Blob Storage container."""

    def __init__(
        self,
        *,
        container_name: str,
        connection_string: Optional[str] = None,
    ):
        if not container_name or not connection_string:
            raise BlobStorageConfigError("AZURE_STORAGE_CONTAINER_NAME and AZURE_STORAGE_CONNECTION_STRING are required.")

        service_client = BlobServiceClient.from_connection_string(connection_string)
        self._container_name = container_name
        self._container_client = service_client.get_container_client(container_name)
        self._ensure_container_exists()

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
        blob_url = await anyio.to_thread.run_sync(
            self._upload_bytes,
            blob_name,
            content,
            content_type,
        )
        return blob_url

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

    @staticmethod
    def _build_blob_name(meeting_id: str, original_filename: str) -> str:
        safe_name = pathlib.Path(original_filename or "uploaded_file").name.replace(" ", "_")
        suffix = safe_name or f"file-{uuid.uuid4()}"
        return f"{meeting_id}/{suffix}"
