from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_503_SERVICE_UNAVAILABLE

from backend.api.auth.sessions import AuthSession, AuthUnavailable, SessionStore
from backend.api.auth.settings import AuthSettings
from backend.api.auth.tokens import verify_token
from backend.api.resources import ApiResources

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings.from_env()


def get_session_store(
    request: Request, settings: Annotated[AuthSettings, Depends(get_auth_settings)]
) -> SessionStore:
    resources: ApiResources = request.app.state.resources
    return SessionStore(resources.redis, settings)


def get_client_ip(
    request: Request, settings: Annotated[AuthSettings, Depends(get_auth_settings)]
) -> str:
    hops = settings.trusted_proxy_hops
    if hops > 0 and "x-forwarded-for" in request.headers:
        parts = [p.strip() for p in request.headers["x-forwarded-for"].split(",")]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "127.0.0.1"


async def require_session(
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthSession:
    if not creds or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication credentials",
        )

    try:
        payload = verify_token(creds.credentials, settings)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid token")

    sid = payload.get("sid")
    if not sid:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        session = await session_store.get_session(sid)
    except AuthUnavailable:
        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        )

    if not session:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="Session expired or invalid"
        )

    return session
