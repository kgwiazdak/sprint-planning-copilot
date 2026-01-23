from __future__ import annotations

import json
import jwt
import logging
import time
import urllib.request
from dataclasses import dataclass
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Any

from backend import audit
from backend.settings import AtlassianOAuthSettings, AzureADSettings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AuthenticatedUser:
    subject: str
    name: str | None
    tenant_id: str | None
    roles: list[str]
    claims: dict[str, Any]
    access_token: str | None = None

    @property
    def audit_id(self) -> str:
        return self.subject or "anonymous"


class AzureADTokenValidator:
    """Validates Azure AD access tokens using the tenant JWKS."""

    def __init__(self, settings: AzureADSettings, *, cache_ttl_seconds: int = 3600) -> None:
        self._settings = settings
        self._cache_ttl = cache_ttl_seconds
        self._jwks_cache: tuple[float, list[dict[str, Any]]] | None = None

    def validate(self, token: str) -> dict[str, Any]:
        if not token:
            raise ValueError("Token is missing")
        headers = jwt.get_unverified_header(token)
        kid = headers.get("kid")
        if not kid:
            raise ValueError("Token does not contain a key identifier")

        key_data = self._get_jwk(kid)
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
        issuer = self._settings.issuer or f"https://sts.windows.net/{self._settings.tenant_id}/"
        audiences = [aud for aud in (self._settings.audience, self._settings.client_id) if aud]
        if not audiences:
            raise RuntimeError("Azure AD audiences are not configured.")

        options = {"require": ["exp", "iat", "iss", "aud", "sub"]}
        return jwt.decode(
            token,
            public_key,
            algorithms=[key_data.get("alg", "RS256")],
            audience=audiences,
            issuer=issuer,
            options=options,
        )

    def _get_jwk(self, kid: str) -> dict[str, Any]:
        keys = self._load_jwks()
        for key in keys:
            if key.get("kid") == kid:
                return key
        # Cache refresh and retry
        self._jwks_cache = None
        keys = self._load_jwks()
        for key in keys:
            if key.get("kid") == kid:
                return key
        raise ValueError(f"Unable to find signing key for kid={kid}")

    def _load_jwks(self) -> list[dict[str, Any]]:
        if self._jwks_cache and time.time() - self._jwks_cache[0] < self._cache_ttl:
            return self._jwks_cache[1]
        if self._settings.jwks:
            parsed = json.loads(self._settings.jwks)
            keys = parsed.get("keys", [])
        else:
            url = self._settings.jwks_url or self._build_discovery_url()
            with urllib.request.urlopen(url, timeout=10) as response:
                payload = response.read()
            document = json.loads(payload.decode("utf-8"))
            keys = document.get("keys", [])
        self._jwks_cache = (time.time(), keys)
        return keys

    def _build_discovery_url(self) -> str:
        tenant = self._settings.tenant_id
        if not tenant:
            raise RuntimeError("AZURE_AD_TENANT_ID is required to discover JWKS.")
        return f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"


class AtlassianTokenValidator:
    """Validates Atlassian OAuth access tokens using the platform JWKS."""

    def __init__(self, settings: AtlassianOAuthSettings, *, cache_ttl_seconds: int = 3600) -> None:
        self._settings = settings
        self._cache_ttl = cache_ttl_seconds
        self._jwks_cache: tuple[float, list[dict[str, Any]]] | None = None

    def validate(self, token: str) -> dict[str, Any]:
        if not token:
            raise ValueError("Token is missing")
        headers = jwt.get_unverified_header(token)
        kid = headers.get("kid")
        if not kid:
            raise ValueError("Token does not contain a key identifier")

        key_data = self._get_jwk(kid)
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
        issuer = self._settings.issuer or "https://auth.atlassian.com"
        audiences = [aud for aud in (self._settings.client_id, self._settings.audience) if aud]
        if not audiences:
            raise RuntimeError("Atlassian OAuth audiences are not configured.")

        options = {"require": ["exp", "iat", "iss", "aud", "sub"]}
        return jwt.decode(
            token,
            public_key,
            algorithms=[key_data.get("alg", "RS256")],
            audience=audiences,
            issuer=issuer,
            options=options,
        )

    def _get_jwk(self, kid: str) -> dict[str, Any]:
        keys = self._load_jwks()
        for key in keys:
            if key.get("kid") == kid:
                return key
        self._jwks_cache = None
        keys = self._load_jwks()
        for key in keys:
            if key.get("kid") == kid:
                return key
        raise ValueError(f"Unable to find signing key for kid={kid}")

    def _load_jwks(self) -> list[dict[str, Any]]:
        if self._jwks_cache and time.time() - self._jwks_cache[0] < self._cache_ttl:
            return self._jwks_cache[1]
        if self._settings.jwks:
            parsed = json.loads(self._settings.jwks)
            keys = parsed.get("keys", [])
        else:
            url = self._settings.jwks_url or "https://auth.atlassian.com/.well-known/jwks.json"
            with urllib.request.urlopen(url, timeout=10) as response:
                payload = response.read()
            document = json.loads(payload.decode("utf-8"))
            keys = document.get("keys", [])
        self._jwks_cache = (time.time(), keys)
        return keys


_validator: AzureADTokenValidator | None = None
_atlassian_validator: AtlassianTokenValidator | None = None


def _get_validator() -> AzureADTokenValidator | None:
    global _validator
    settings = get_settings().azure_ad
    if not settings.enabled:
        return None
    if _validator is None:
        _validator = AzureADTokenValidator(settings=settings)
    return _validator


def _get_atlassian_validator() -> AtlassianTokenValidator | None:
    global _atlassian_validator
    settings = get_settings().atlassian_oauth
    if not settings.enabled:
        return None
    if _atlassian_validator is None:
        _atlassian_validator = AtlassianTokenValidator(settings=settings)
    return _atlassian_validator


async def require_authenticated_user(
        credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    settings = get_settings()
    atl_enabled = settings.atlassian_oauth.enabled
    azure_enabled = settings.azure_ad.enabled
    logger.info(
        "auth.require start",
        extra={
            "azure_enabled": azure_enabled,
            "azure_require_auth": settings.azure_ad.require_auth,
            "atl_enabled": atl_enabled,
            "atl_require_auth": settings.atlassian_oauth.require_auth,
            "credentials_provided": bool(credentials and credentials.credentials),
        },
    )

    def _anonymous():
        anon = AuthenticatedUser(subject="anonymous", name=None, tenant_id=None, roles=[], claims={})
        audit_token = audit.bind_actor(anon.audit_id)
        return anon, audit_token

    if not atl_enabled and not azure_enabled:
        user, audit_token = _anonymous()
        try:
            yield user
        finally:
            audit.reset_actor(audit_token)

    if not credentials:
        logger.warning("auth.require missing credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing.")

    if atl_enabled:
        validator = _get_atlassian_validator()
        if validator is None:
            logger.error("auth.require atlassian validator unavailable")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Atlassian auth not configured.")
        try:
            claims = validator.validate(credentials.credentials)
        except Exception as exc:
            logger.warning("auth.require atlassian token invalid: %s", exc)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token.") from exc
        user = AuthenticatedUser(
            subject=claims.get("sub") or "anonymous",
            name=claims.get("name") or claims.get("email"),
            tenant_id=claims.get("aud"),
            roles=list(claims.get("roles") or claims.get("groups") or []),
            claims=claims,
            access_token=credentials.credentials,
        )
    else:
        validator = _get_validator()
        if validator is None:
            logger.error("auth.require azure validator unavailable")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Azure AD not configured.")
        try:
            claims = validator.validate(credentials.credentials)
        except Exception as exc:
            logger.warning("auth.require azure token invalid: %s", exc)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token.") from exc
        user = AuthenticatedUser(
            subject=claims.get("sub") or claims.get("oid") or "anonymous",
            name=claims.get("name") or claims.get("preferred_username"),
            tenant_id=claims.get("tid"),
            roles=list(claims.get("roles") or claims.get("groups") or []),
            claims=claims,
            access_token=None,
        )

    audit_token = audit.bind_actor(user.audit_id)
    try:
        yield user
    finally:
        audit.reset_actor(audit_token)
