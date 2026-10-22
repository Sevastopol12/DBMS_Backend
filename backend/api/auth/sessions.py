import asyncio
import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import redis

from backend.api.auth.settings import AuthSettings
from backend.api.auth.tokens import create_token
from backend.timezone import now_utc


class AuthUnavailable(Exception):
    """Raised when Redis is unavailable or times out."""


class RefreshInvalid(Exception):
    """Raised when a refresh token is expired, unknown or out of its window."""


class RefreshReuseDetected(Exception):
    """Raised when a rotated refresh token is replayed after the grace window."""


@dataclass(frozen=True)
class AuthSession:
    user_id: UUID
    facility_id: UUID
    sid: str


@dataclass(frozen=True)
class SessionGrant:
    sid: str
    session_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    session_expires_at: datetime


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _session_key(sid: str) -> str:
    return f"auth:session:{sid}"


def _refresh_key(token_hash: str) -> str:
    return f"auth:refresh:{token_hash}"


def _millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


class SessionStore:
    def __init__(
        self,
        client: redis.Redis,
        settings: AuthSettings,
        *,
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self._client = client
        self._settings = settings
        self._clock = clock

    async def create_session(self, user_id: UUID, facility_id: UUID) -> SessionGrant:
        def _create() -> SessionGrant:
            try:
                now = self._clock()
                session_expires_at = now + timedelta(
                    seconds=self._settings.session_ttl_seconds
                )
                access_expires_at = min(
                    now + timedelta(seconds=self._settings.access_ttl_seconds),
                    session_expires_at,
                )
                refresh_expires_at = min(
                    now + timedelta(seconds=self._settings.refresh_ttl_seconds),
                    session_expires_at,
                )
                sid = secrets.token_urlsafe(32)
                refresh_token = secrets.token_urlsafe(32)
                refresh_hash = _hash_token(refresh_token)
                session_expires_at_ms = _millis(session_expires_at)
                session_token = create_token(
                    user_id,
                    sid,
                    self._settings,
                    expires_at=access_expires_at,
                    issued_at=now,
                )
                data = json.dumps(
                    {
                        "user_id": str(user_id),
                        "facility_id": str(facility_id),
                        "refresh_hash": refresh_hash,
                        "prev_refresh_hash": None,
                        "refresh_expires_at": refresh_expires_at.isoformat(),
                        "rotated_at": None,
                        "session_expires_at": session_expires_at.isoformat(),
                    }
                )

                pipe = self._client.pipeline()
                pipe.set(_session_key(sid), data, pxat=session_expires_at_ms)
                pipe.set(
                    _refresh_key(refresh_hash),
                    sid,
                    pxat=min(_millis(refresh_expires_at), session_expires_at_ms),
                )
                pipe.execute()
            except redis.RedisError as e:
                raise AuthUnavailable from e

            return SessionGrant(
                sid=sid,
                session_token=session_token,
                refresh_token=refresh_token,
                access_expires_at=access_expires_at,
                refresh_expires_at=refresh_expires_at,
                session_expires_at=session_expires_at,
            )

        return await asyncio.to_thread(_create)

    async def rotate(self, refresh_token: str) -> SessionGrant:
        presented_hash = _hash_token(refresh_token)

        def _rotate() -> SessionGrant:
            try:
                for _ in range(self._settings.max_rotate_attempts):
                    try:
                        return self._rotate_once(presented_hash)
                    except redis.WatchError:
                        continue
            except redis.RedisError as e:
                raise AuthUnavailable from e

            raise AuthUnavailable

        return await asyncio.to_thread(_rotate)

    def _rotate_once(self, presented_hash: str) -> SessionGrant:
        sid_raw = self._client.get(_refresh_key(presented_hash))
        if sid_raw is None:
            raise RefreshInvalid
        sid = sid_raw.decode("utf-8") if isinstance(sid_raw, bytes) else sid_raw

        session_key = _session_key(sid)
        pipe = self._client.pipeline()
        try:
            pipe.watch(session_key)
            raw = pipe.get(session_key)
            if raw is None:
                raise RefreshInvalid

            try:
                data = json.loads(raw)
                now = self._clock()
                session_expires_at = datetime.fromisoformat(data["session_expires_at"])
                current_hash = data.get("refresh_hash")
                prev_hash = data.get("prev_refresh_hash")
            except (ValueError, KeyError, TypeError):
                raise RefreshInvalid from None

            if now >= session_expires_at:
                raise RefreshInvalid

            if presented_hash == current_hash:
                refresh_expires_at = datetime.fromisoformat(data["refresh_expires_at"])
                if now >= refresh_expires_at:
                    raise RefreshInvalid
            elif presented_hash == prev_hash:
                rotated_at_raw = data.get("rotated_at")
                if rotated_at_raw is None:
                    raise RefreshInvalid
                try:
                    rotated_at = datetime.fromisoformat(rotated_at_raw)
                except (ValueError, TypeError):
                    raise RefreshInvalid from None
                grace = timedelta(seconds=self._settings.refresh_grace_seconds)
                if now - rotated_at > grace:
                    pipe.unwatch()
                    self._destroy_keys(sid, {presented_hash, current_hash, prev_hash})
                    raise RefreshReuseDetected
            else:
                raise RefreshInvalid

            new_refresh_token = secrets.token_urlsafe(32)
            new_hash = _hash_token(new_refresh_token)
            access_expires_at = min(
                now + timedelta(seconds=self._settings.access_ttl_seconds),
                session_expires_at,
            )
            new_refresh_expires_at = min(
                now + timedelta(seconds=self._settings.refresh_ttl_seconds),
                session_expires_at,
            )
            session_expires_at_ms = _millis(session_expires_at)
            session_token = create_token(
                UUID(str(data["user_id"])),
                sid,
                self._settings,
                expires_at=access_expires_at,
                issued_at=now,
            )
            updated = json.dumps(
                {
                    "user_id": data["user_id"],
                    "facility_id": data["facility_id"],
                    "refresh_hash": new_hash,
                    "prev_refresh_hash": current_hash,
                    "refresh_expires_at": new_refresh_expires_at.isoformat(),
                    "rotated_at": now.isoformat(),
                    "session_expires_at": session_expires_at.isoformat(),
                }
            )

            pipe.multi()
            pipe.set(session_key, updated, pxat=session_expires_at_ms)
            pipe.set(
                _refresh_key(new_hash),
                sid,
                pxat=min(_millis(new_refresh_expires_at), session_expires_at_ms),
            )
            if prev_hash and prev_hash not in (new_hash, current_hash):
                pipe.delete(_refresh_key(prev_hash))
            pipe.execute()
        finally:
            pipe.reset()

        return SessionGrant(
            sid=sid,
            session_token=session_token,
            refresh_token=new_refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=new_refresh_expires_at,
            session_expires_at=session_expires_at,
        )

    def _destroy_keys(self, sid: str, token_hashes: set[str | None]) -> None:
        pipe = self._client.pipeline()
        pipe.delete(_session_key(sid))
        for token_hash in token_hashes:
            if token_hash:
                pipe.delete(_refresh_key(token_hash))
        pipe.execute()

    async def get_session(self, sid: str) -> AuthSession | None:
        def _get() -> str | None:
            try:
                return self._client.get(_session_key(sid))
            except redis.RedisError as e:
                raise AuthUnavailable from e

        data = await asyncio.to_thread(_get)
        if not data:
            return None

        try:
            parsed = json.loads(data)
            return AuthSession(
                user_id=UUID(parsed["user_id"]),
                facility_id=UUID(parsed["facility_id"]),
                sid=sid,
            )
        except (ValueError, KeyError, TypeError):
            return None

    async def destroy_session(self, user_id: UUID, sid: str) -> None:
        def _destroy() -> None:
            try:
                raw = self._client.get(_session_key(sid))
                token_hashes: set[str | None] = set()
                if raw:
                    try:
                        data = json.loads(raw)
                        token_hashes = {
                            data.get("refresh_hash"),
                            data.get("prev_refresh_hash"),
                        }
                    except (ValueError, TypeError):
                        token_hashes = set()
                self._destroy_keys(sid, token_hashes)
            except redis.RedisError as e:
                raise AuthUnavailable from e

        await asyncio.to_thread(_destroy)


__all__ = [
    "AuthSession",
    "AuthUnavailable",
    "RefreshInvalid",
    "RefreshReuseDetected",
    "SessionGrant",
    "SessionStore",
]
