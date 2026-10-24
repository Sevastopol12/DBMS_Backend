from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import WebSocket

from backend.api.auth.dependencies import resolve_session_token
from backend.api.auth.sessions import AuthSession, SessionStore
from backend.api.auth.settings import AuthSettings


@dataclass(frozen=True)
class WebSocketAuth:
    session: AuthSession
    claims: dict[str, Any]


async def websocket_session(
    websocket: WebSocket, settings: AuthSettings, store: SessionStore
) -> WebSocketAuth:
    authorization = websocket.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise jwt.InvalidTokenError("missing bearer token")
    session, payload = await resolve_session_token(token, settings, store)
    return WebSocketAuth(session, payload)


__all__ = ["WebSocketAuth", "websocket_session"]
