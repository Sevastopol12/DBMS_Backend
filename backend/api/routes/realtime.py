import asyncio
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from redis import RedisError

from backend.api.auth.dependencies import (
    get_auth_settings,
    get_websocket_session_store,
)
from backend.api.auth.sessions import (
    AuthUnavailable,
    RefreshInvalid,
    RefreshReuseDetected,
    SessionStore,
)
from backend.api.auth.settings import AuthSettings
from backend.api.auth.websocket import websocket_session
from backend.api.realtime.hub import RealtimeHub
from backend.api.realtime.messages import (
    INCOMING_FRAME_ADAPTER,
    ProtocolError,
    SessionExpiring,
    SessionRefresh,
    SessionRefreshed,
)
from backend.api.resources import ApiResources
from backend.timezone import now_utc

logger = logging.getLogger(__name__)
router = APIRouter()
_MAX_FRAME_BYTES = 4096


@router.websocket("/ws")
async def realtime_ws(
    websocket: WebSocket,
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    session_store: Annotated[SessionStore, Depends(get_websocket_session_store)],
) -> None:
    await websocket.accept()
    resources: ApiResources = websocket.app.state.resources
    try:
        auth = await websocket_session(websocket, settings, session_store)
    except AuthUnavailable:
        await websocket.close(code=1013)
        return
    except (jwt.InvalidTokenError, ValidationError):
        await websocket.close(code=4401)
        return

    session = auth.session
    sid = session.sid
    cid_raw = auth.claims.get("cid")
    cid = str(cid_raw) if cid_raw else None
    connection_id = secrets.token_urlsafe(16)
    hub: RealtimeHub = websocket.app.state.hub
    if cid:
        try:
            if not await session_store.claim_ws(sid, cid, connection_id):
                await websocket.close(code=4401)
                return
        except AuthUnavailable:
            await websocket.close(code=1013)
            return

    connection = hub.connect(websocket, session.facility_id, sid, cid)
    try:
        session_expiry = await _session_expiry(resources.redis, sid)
        refresh_expiry = None
        if cid:
            expiries = await session_store.chain_expiries(sid, cid)
            if expiries is None:
                await hub.disconnect(connection, 4401)
                return
            session_expiry, refresh_expiry = expiries
    except AuthUnavailable:
        await hub.disconnect(connection, 1013)
        return

    state = {
        "access_expires_at": _token_expiry(
            websocket.headers.get("authorization", ""), settings
        ),
        "session_expires_at": session_expiry,
        "refresh_expires_at": refresh_expiry,
    }
    refresh_changed = asyncio.Event()

    async def receive() -> int:
        try:
            while True:
                message = await websocket.receive()
                raw = message.get("text")
                if raw is None:
                    return 1003
                if len(raw.encode("utf-8")) > _MAX_FRAME_BYTES:
                    return 1009
                try:
                    frame = INCOMING_FRAME_ADAPTER.validate_python(json.loads(raw))
                except (ValueError, TypeError, ValidationError):
                    continue
                if not isinstance(frame, SessionRefresh):
                    continue
                if cid is None:
                    return 4401
                try:
                    if not await session_store.owns_ws(sid, cid, connection_id):
                        return 4409
                except AuthUnavailable:
                    return 1013
                try:
                    grant = await session_store.rotate(
                        frame.refresh_token, expected_sid=sid, expected_cid=cid
                    )
                except RefreshInvalid:
                    hub.send(
                        connection,
                        ProtocolError(
                            code="refresh_invalid", message="Refresh token is invalid"
                        ),
                    )
                    await hub.flush(connection)
                    return 4401
                except RefreshReuseDetected:
                    return 4403
                except AuthUnavailable:
                    hub.send(
                        connection,
                        ProtocolError(
                            code="unavailable",
                            message="Authentication service unavailable",
                        ),
                    )
                    await hub.flush(connection)
                    return 1013
                if grant.sid != sid or grant.cid != cid:
                    return 4401
                state["access_expires_at"] = grant.access_expires_at
                state["refresh_expires_at"] = grant.refresh_expires_at
                state["session_expires_at"] = grant.session_expires_at
                refresh_changed.set()
                hub.send(
                    connection,
                    SessionRefreshed(
                        session_token=grant.session_token,
                        refresh_token=grant.refresh_token,
                        access_expires_at=grant.access_expires_at,
                        refresh_expires_at=grant.refresh_expires_at,
                    ),
                )
        except WebSocketDisconnect:
            connection.client_disconnected = True
            return 1000

    async def timers() -> int:
        warned_for: datetime | None = None
        next_revalidate = now_utc()
        while True:
            now = now_utc()
            session_expires_at = state["session_expires_at"]
            access_expires_at = state["access_expires_at"]
            if now >= session_expires_at:
                return 4401
            if access_expires_at is not None and now >= access_expires_at:
                return 4401
            if access_expires_at is not None:
                warning_at = access_expires_at - timedelta(
                    seconds=settings.ws_expiry_warning_seconds
                )
                if now >= warning_at and warned_for != access_expires_at:
                    hub.send(
                        connection,
                        SessionExpiring(
                            expires_in=max(
                                0, int((access_expires_at - now).total_seconds())
                            )
                        ),
                    )
                    warned_for = access_expires_at
            if now >= next_revalidate:
                try:
                    if await session_store.get_session(sid, cid) is None:
                        return 4401
                    if cid and not await session_store.owns_ws(sid, cid, connection_id):
                        return 4409
                except AuthUnavailable:
                    return 1013
                next_revalidate = now + timedelta(
                    seconds=settings.ws_revalidate_seconds
                )
            deadlines = [next_revalidate, session_expires_at]
            if access_expires_at is not None:
                deadlines.append(access_expires_at)
                if warned_for != access_expires_at:
                    deadlines.append(
                        access_expires_at
                        - timedelta(seconds=settings.ws_expiry_warning_seconds)
                    )
            wait_seconds = max(
                0.05,
                min((deadline - now).total_seconds() for deadline in deadlines),
            )
            if refresh_changed.is_set():
                refresh_changed.clear()
                continue
            try:
                await asyncio.wait_for(refresh_changed.wait(), timeout=wait_seconds)
            except TimeoutError:
                pass
            else:
                refresh_changed.clear()

    receiver_task = asyncio.create_task(receive())
    timer_task = asyncio.create_task(timers())
    writer_task = connection.writer_task
    tasks = [receiver_task, timer_task]
    if writer_task is not None:
        tasks.append(writer_task)
    code = 1011
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if writer_task in done:
            code = 1000 if writer_task.cancelled() else 1013
        else:
            code = next(iter(done)).result()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await hub.disconnect(connection, code)


def _token_expiry(authorization: str, settings: AuthSettings) -> datetime | None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False, "verify_iat": False},
        )
        return datetime.fromtimestamp(payload["exp"], tz=now_utc().tzinfo)
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError, OverflowError):
        return None


async def _session_expiry(client, sid: str) -> datetime:
    # The session expiry is normally available from grant fields only after refresh;
    # retrieve the creation-time deadline from the existing Redis session record.
    try:
        raw = await asyncio.to_thread(client.get, f"auth:session:{sid}")
    except RedisError as exc:
        raise AuthUnavailable from exc
    if raw is None:
        return now_utc()
    try:
        data = json.loads(raw)
        return datetime.fromisoformat(data["session_expires_at"])
    except (ValueError, TypeError, KeyError):
        return now_utc()


__all__ = ["router"]
