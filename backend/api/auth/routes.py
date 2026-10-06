from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from starlette.status import (
    HTTP_204_NO_CONTENT,
    HTTP_401_UNAUTHORIZED,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from backend.api.auth.dependencies import (
    bearer_scheme,
    get_auth_settings,
    get_client_ip,
    get_session_store,
)
from backend.api.auth.ratelimit import RateLimiter, RateLimitExceeded
from backend.api.auth.service import AuthenticationFailed, AuthService
from backend.api.auth.sessions import AuthUnavailable, SessionStore
from backend.api.auth.settings import AuthSettings
from backend.api.auth.tokens import verify_token
from backend.api.resources import ApiResources
from backend.database.service.auth.repository import AuthRepository

auth_router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


def get_auth_service(
    request: Request,
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> AuthService:
    resources: ApiResources = request.app.state.resources
    rate_limiter = RateLimiter(resources.redis, settings)
    # create repo with application engine
    repository = AuthRepository(resources.application)
    return AuthService(settings, session_store, rate_limiter, repository)


@auth_router.post("/login", response_model=None)
async def login(
    req: LoginRequest,
    ip: Annotated[str, Depends(get_client_ip)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, Any]:
    try:
        return await service.login(req.username, req.password, ip)
    except RateLimitExceeded as e:
        headers = {"Retry-After": str(e.retry_after)}
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers=headers,
        )
    except AuthenticationFailed:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    except AuthUnavailable:
        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        )


@auth_router.post("/logout", status_code=HTTP_204_NO_CONTENT)
async def logout(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
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
    sub = payload.get("sub")
    if not sid or not sub:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid token")
    try:
        user_id = UUID(str(sub))
    except ValueError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid token")
    try:
        await service.logout(user_id, sid)
    except AuthUnavailable:
        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        )
