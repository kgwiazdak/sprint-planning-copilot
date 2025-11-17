from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.presentation.http.security import AzureADTokenValidator
from backend.settings import AzureADSettings


def _generate_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def _build_jwk(public_key, kid: str) -> dict:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(public_key)
    data = json.loads(jwk)
    data["kid"] = kid
    data["alg"] = "RS256"
    return data


def _encode(private_key, kid: str, payload: dict) -> str:
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(payload, key_bytes, algorithm="RS256", headers={"kid": kid})


def test_validator_accepts_valid_token():
    private_key, public_key = _generate_keys()
    kid = "kid-test"
    jwk = _build_jwk(public_key, kid)
    settings = AzureADSettings(
        tenant_id="tenant-id",
        client_id="client-id",
        audience="api://client-id",
        issuer="https://sts.windows.net/tenant-id/",
        jwks=json.dumps({"keys": [jwk]}),
        require_auth=True,
    )
    validator = AzureADTokenValidator(settings)
    now = int(time.time())
    token = _encode(
        private_key,
        kid,
        {
            "sub": "user-123",
            "aud": "api://client-id",
            "iss": "https://sts.windows.net/tenant-id/",
            "iat": now,
            "exp": now + 600,
            "tid": "tenant-id",
        },
    )

    claims = validator.validate(token)

    assert claims["sub"] == "user-123"
    assert claims["tid"] == "tenant-id"


def test_validator_rejects_unknown_kid():
    private_key, public_key = _generate_keys()
    jwk = _build_jwk(public_key, "kid-valid")
    settings = AzureADSettings(
        tenant_id="tenant-id",
        client_id="client-id",
        audience="api://client-id",
        issuer="https://sts.windows.net/tenant-id/",
        jwks=json.dumps({"keys": [jwk]}),
        require_auth=True,
    )
    validator = AzureADTokenValidator(settings)
    now = int(time.time())
    token = _encode(
        private_key,
        "kid-missing",
        {
            "sub": "user-123",
            "aud": "api://client-id",
            "iss": "https://sts.windows.net/tenant-id/",
            "iat": now,
            "exp": now + 600,
            "tid": "tenant-id",
        },
    )

    with pytest.raises(ValueError):
        validator.validate(token)
