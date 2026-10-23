import jwt
from fastapi import WebSocket

from backend.api.auth.sessions import AuthSession, SessionStore
from backend.api.auth.settings import AuthSettings
from backend.api.auth.tokens import verify_token


async def websocket_session(
    websocket: WebSocket, settings: AuthSettings, store: SessionStore
) -> AuthSession:
    authorization = websocket.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise jwt.InvalidTokenError("missing bearer token")
    payload = verify_token(token, settings)
    sid = payload.get("sid")
    if not sid:
        raise jwt.InvalidTokenError("missing session id")
    session = await store.get_session(str(sid))
    if session is None:
        raise jwt.InvalidTokenError("session missing")
    return session


__all__ = ["websocket_session"]
