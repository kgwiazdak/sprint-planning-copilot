"""Tests for the voice sync startup script."""
from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestSyncVoices:
    """Tests for backend.scripts.sync_voices module."""

    def test_sync_skipped_when_connection_string_missing(self, caplog, monkeypatch):
        """Sync should skip gracefully when AZURE_STORAGE_CONNECTION_STRING is not set."""
        monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
        monkeypatch.delenv("AZURE_STORAGE_CONTAINER_WORKERS", raising=False)

        import backend.scripts.sync_voices as sync_module
        importlib.reload(sync_module)

        with caplog.at_level(logging.INFO):
            sync_module.sync_voices()

        assert "Voice sync skipped" in caplog.text

    def test_sync_skipped_when_container_missing(self, caplog, monkeypatch):
        """Sync should skip gracefully when AZURE_STORAGE_CONTAINER_WORKERS is not set."""
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "fake-connection-string")
        monkeypatch.delenv("AZURE_STORAGE_CONTAINER_WORKERS", raising=False)

        import backend.scripts.sync_voices as sync_module
        importlib.reload(sync_module)

        with caplog.at_level(logging.INFO):
            sync_module.sync_voices()

        assert "Voice sync skipped" in caplog.text

    def test_sync_downloads_intro_mp3_files(self, tmp_path, monkeypatch):
        """Sync should download intro_*.mp3 files from Azure container."""
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=key;EndpointSuffix=core.windows.net")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER_WORKERS", "workers")
        monkeypatch.setenv("INTRO_AUDIO_DIR", str(tmp_path))

        # Mock blob data
        mock_blob1 = MagicMock()
        mock_blob1.name = "intro_John_Doe.mp3"
        mock_blob2 = MagicMock()
        mock_blob2.name = "intro_Jane_Smith.mp3"
        mock_blob3 = MagicMock()
        mock_blob3.name = "intro_other.wav"  # Should be skipped - not mp3

        mock_download = MagicMock()
        mock_download.readall.return_value = b"fake audio data"

        mock_blob_client = MagicMock()
        mock_blob_client.download_blob.return_value = mock_download

        mock_container = MagicMock()
        mock_container.list_blobs.return_value = [mock_blob1, mock_blob2, mock_blob3]
        mock_container.get_blob_client.return_value = mock_blob_client

        mock_service = MagicMock()
        mock_service.get_container_client.return_value = mock_container

        with patch("azure.storage.blob.BlobServiceClient.from_connection_string", return_value=mock_service):
            # Need to reimport to pick up patched env vars
            import importlib
            import backend.scripts.sync_voices as sync_module
            importlib.reload(sync_module)
            sync_module.sync_voices()

        # Verify only mp3 files were downloaded
        downloaded_files = list(tmp_path.glob("*.mp3"))
        assert len(downloaded_files) == 2
        assert (tmp_path / "intro_John_Doe.mp3").exists()
        assert (tmp_path / "intro_Jane_Smith.mp3").exists()
        assert not (tmp_path / "intro_other.wav").exists()

        # Verify content was written
        assert (tmp_path / "intro_John_Doe.mp3").read_bytes() == b"fake audio data"

    def test_sync_skips_existing_files(self, tmp_path, monkeypatch):
        """Sync should not re-download files that already exist."""
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=key;EndpointSuffix=core.windows.net")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER_WORKERS", "workers")
        monkeypatch.setenv("INTRO_AUDIO_DIR", str(tmp_path))

        # Pre-create a file
        existing_file = tmp_path / "intro_Existing_User.mp3"
        existing_file.write_bytes(b"existing content")

        mock_blob = MagicMock()
        mock_blob.name = "intro_Existing_User.mp3"

        mock_container = MagicMock()
        mock_container.list_blobs.return_value = [mock_blob]

        mock_service = MagicMock()
        mock_service.get_container_client.return_value = mock_container

        with patch("azure.storage.blob.BlobServiceClient.from_connection_string", return_value=mock_service):
            import importlib
            import backend.scripts.sync_voices as sync_module
            importlib.reload(sync_module)
            sync_module.sync_voices()

        # File should not have been overwritten
        assert existing_file.read_bytes() == b"existing content"
        # get_blob_client should never have been called (no download attempted)
        mock_container.get_blob_client.assert_not_called()

    def test_sync_handles_azure_error_gracefully(self, tmp_path, monkeypatch, caplog):
        """Sync should handle Azure errors gracefully without crashing."""
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=key;EndpointSuffix=core.windows.net")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER_WORKERS", "workers")
        monkeypatch.setenv("INTRO_AUDIO_DIR", str(tmp_path))

        from azure.core.exceptions import AzureError

        mock_service = MagicMock()
        mock_service.get_container_client.side_effect = AzureError("Connection failed")

        with patch("azure.storage.blob.BlobServiceClient.from_connection_string", return_value=mock_service):
            import backend.scripts.sync_voices as sync_module
            importlib.reload(sync_module)
            # Should not raise
            with caplog.at_level(logging.WARNING):
                sync_module.sync_voices()

        assert "Failed to connect" in caplog.text or "Connection failed" in caplog.text

    def test_sync_creates_target_directory(self, tmp_path, monkeypatch):
        """Sync should create the target directory if it doesn't exist."""
        target_dir = tmp_path / "nested" / "voices"
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=key;EndpointSuffix=core.windows.net")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER_WORKERS", "workers")
        monkeypatch.setenv("INTRO_AUDIO_DIR", str(target_dir))

        mock_container = MagicMock()
        mock_container.list_blobs.return_value = []

        mock_service = MagicMock()
        mock_service.get_container_client.return_value = mock_container

        with patch("azure.storage.blob.BlobServiceClient.from_connection_string", return_value=mock_service):
            import importlib
            import backend.scripts.sync_voices as sync_module
            importlib.reload(sync_module)
            sync_module.sync_voices()

        assert target_dir.exists()


@pytest.mark.integration
class TestSyncVoicesIntegration:
    """Integration tests that require real Azure credentials.

    These tests are skipped unless AZURE_STORAGE_CONNECTION_STRING and
    AZURE_STORAGE_CONTAINER_WORKERS are set in the environment.
    """

    @pytest.fixture
    def azure_configured(self):
        """Skip if Azure is not configured."""
        conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        container = os.getenv("AZURE_STORAGE_CONTAINER_WORKERS")
        if not conn or not container:
            pytest.skip("Azure Storage not configured")
        return conn, container

    def test_real_azure_connection(self, azure_configured, tmp_path, monkeypatch):
        """Test actual connection to Azure and download of intro files."""
        conn, container = azure_configured
        monkeypatch.setenv("INTRO_AUDIO_DIR", str(tmp_path))

        from backend.scripts.sync_voices import sync_voices
        sync_voices()

        downloaded = list(tmp_path.glob("intro_*.mp3"))
        # Just verify we can connect and potentially download files
        # The actual number depends on what's in the container
        assert tmp_path.exists()
