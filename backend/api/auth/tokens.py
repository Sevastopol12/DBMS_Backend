from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt

from backend.api.auth.settings import AuthSettings


def create_token(user_id: UUID, sid: str, settings: AuthSettings) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": sid,
        "iat": now,
        "exp": now + timedelta(seconds=settings.session_ttl_seconds),
    }
    if settings.jwt_issuer:
        payload["iss"] = settings.jwt_issuer
    if settings.jwt_audience:
        payload["aud"] = settings.jwt_audience

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_token(token: str, settings: AuthSettings) -> dict[str, Any]:
    """Decode and verify JWT. Raises jwt.InvalidTokenError on failure."""
    kwargs: dict[str, Any] = {
        "algorithms": [settings.jwt_algorithm],
        "leeway": 30,
        "options": {
            "require": ["exp", "iat", "sub", "sid"],
        },
    }
    if settings.jwt_issuer:
        kwargs["issuer"] = settings.jwt_issuer
        kwargs["options"]["require"].append("iss")
    if settings.jwt_audience:
        kwargs["audience"] = settings.jwt_audience
        kwargs["options"]["require"].append("aud")

    return jwt.decode(token, settings.jwt_secret, **kwargs)
