from __future__ import annotations

from backend.infrastructure.storage.blob import BlobStorageService


def test_clamp_token_ttl_enforces_limits():
    max_ttl = 900
    assert BlobStorageService.clamp_token_ttl(1200, max_seconds=max_ttl) == max_ttl
    assert BlobStorageService.clamp_token_ttl(0, max_seconds=max_ttl) == max_ttl
    assert BlobStorageService.clamp_token_ttl(None, max_seconds=max_ttl) == max_ttl
    assert BlobStorageService.clamp_token_ttl(30, max_seconds=max_ttl) == 60
    assert BlobStorageService.clamp_token_ttl(300, max_seconds=max_ttl) == 300
