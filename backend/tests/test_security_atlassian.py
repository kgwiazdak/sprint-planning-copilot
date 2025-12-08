from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.presentation.http.security import AtlassianTokenValidator
from backend.settings import AtlassianOAuthSettings


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
    settings = AtlassianOAuthSettings(
        client_id="client-id",
        audience="api.atlassian.com",
        issuer="https://auth.atlassian.com",
        jwks=json.dumps({"keys": [jwk]}),
        require_auth=True,
    )
    validator = AtlassianTokenValidator(settings)
    now = int(time.time())
    token = _encode(
        private_key,
        kid,
        {
            "sub": "user-123",
            "aud": "client-id",
            "iss": "https://auth.atlassian.com",
            "iat": now,
            "exp": now + 600,
        },
    )

    claims = validator.validate(token)

    assert claims["sub"] == "user-123"
    assert claims["aud"] == "client-id"


def test_validator_rejects_unknown_kid():
    private_key, public_key = _generate_keys()
    jwk = _build_jwk(public_key, "kid-valid")
    settings = AtlassianOAuthSettings(
        client_id="client-id",
        audience="api.atlassian.com",
        issuer="https://auth.atlassian.com",
        jwks=json.dumps({"keys": [jwk]}),
        require_auth=True,
    )
    validator = AtlassianTokenValidator(settings)
    now = int(time.time())
    token = _encode(
        private_key,
        "kid-missing",
        {
            "sub": "user-123",
            "aud": "client-id",
            "iss": "https://auth.atlassian.com",
            "iat": now,
            "exp": now + 600,
        },
    )

    with pytest.raises(ValueError):
        validator.validate(token)
