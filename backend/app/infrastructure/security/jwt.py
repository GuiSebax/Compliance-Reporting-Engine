"""JWT access-token issuance and verification (PyJWT, HS256).

Scope is deliberately small: one token type (access token), one role
(authenticated user), short expiry, no refresh-token flow. A reporting
engine's API surface is a handful of internal endpoints, not a
multi-tenant public product — adding refresh tokens/roles/scopes now
would be speculative complexity with no current requirement driving it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import get_settings


class TokenError(Exception):
    """Raised for any invalid, expired, or malformed token."""


def create_access_token(*, subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
