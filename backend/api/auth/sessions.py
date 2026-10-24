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
    """Raised when Redis is unavailable or an optimistic transaction keeps conflicting."""


class RefreshInvalid(Exception):
    """A refresh token is unknown, expired, or belongs to another chain."""


class RefreshReuseDetected(Exception):
    """A previous refresh token was replayed outside its grace window."""


@dataclass(frozen=True)
class AuthSession:
    user_id: UUID
    facility_id: UUID
    sid: str


@dataclass(frozen=True)
class SessionGrant:
    sid: str
    cid: str
    session_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    session_expires_at: datetime


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _session_key(sid: str) -> str:
    return f"auth:session:{sid}"


def _user_sid_key(user_id: UUID) -> str:
    return f"auth:user_sid:{user_id}"


def _chains_key(sid: str) -> str:
    return f"auth:chains:{sid}"


def _chain_key(sid: str, cid: str) -> str:
    return f"auth:chain:{sid}:{cid}"


def _refresh_key(token_hash: str) -> str:
    return f"auth:refresh:{token_hash}"


def _ws_key(sid: str, cid: str) -> str:
    return f"auth:ws:{sid}:{cid}"


def _decode(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    return value.decode("utf-8") if isinstance(value, bytes) else value


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

    async def login_session(self, user_id: UUID, facility_id: UUID) -> SessionGrant:
        return await asyncio.to_thread(self._login_session, user_id, facility_id)

    def _login_session(self, user_id: UUID, facility_id: UUID) -> SessionGrant:
        try:
            for _ in range(self._settings.max_rotate_attempts):
                sid, session_expires_at = self._find_or_create_sid(user_id, facility_id)
                grant = self._create_chain(user_id, sid, session_expires_at)
                if grant is not None:
                    return grant
            raise AuthUnavailable
        except redis.RedisError as exc:
            raise AuthUnavailable from exc

    def _find_or_create_sid(
        self, user_id: UUID, facility_id: UUID
    ) -> tuple[str, datetime]:
        index_key = _user_sid_key(user_id)
        for _ in range(self._settings.max_rotate_attempts):
            pipe = self._client.pipeline()
            try:
                pipe.watch(index_key)
                sid = _decode(pipe.get(index_key))
                if sid:
                    raw = self._client.get(_session_key(sid))
                    if raw:
                        try:
                            data = json.loads(raw)
                            expiry = datetime.fromisoformat(data["session_expires_at"])
                        except (ValueError, KeyError, TypeError):
                            pass
                        else:
                            if self._clock() < expiry:
                                pipe.unwatch()
                                return sid, expiry

                now = self._clock()
                sid = secrets.token_urlsafe(32)
                expiry = now + timedelta(seconds=self._settings.session_ttl_seconds)
                expiry_ms = _millis(expiry)
                record = json.dumps(
                    {
                        "user_id": str(user_id),
                        "facility_id": str(facility_id),
                        "session_expires_at": expiry.isoformat(),
                    }
                )
                pipe.multi()
                pipe.set(_session_key(sid), record, pxat=expiry_ms)
                pipe.set(index_key, sid, pxat=expiry_ms)
                pipe.execute()
                return sid, expiry
            except redis.WatchError:
                continue
            finally:
                pipe.reset()
        raise AuthUnavailable

    def _create_chain(
        self, user_id: UUID, sid: str, session_expires_at: datetime
    ) -> SessionGrant | None:
        for _ in range(self._settings.max_rotate_attempts):
            cid = secrets.token_urlsafe(16)
            token = secrets.token_urlsafe(32)
            token_hash = _hash_token(token)
            now = self._clock()
            access_expires_at = min(
                now + timedelta(seconds=self._settings.access_ttl_seconds),
                session_expires_at,
            )
            refresh_expires_at = session_expires_at
            chain = {
                "refresh_hash": token_hash,
                "prev_refresh_hash": None,
                "refresh_expires_at": refresh_expires_at.isoformat(),
                "rotated_at": None,
            }
            pipe = self._client.pipeline()
            try:
                pipe.watch(_session_key(sid), _user_sid_key(user_id))
                session_raw, indexed_sid = pipe.mget(
                    _session_key(sid), _user_sid_key(user_id)
                )
                if not session_raw or _decode(indexed_sid) != sid:
                    pipe.unwatch()
                    return None
                try:
                    session_expires_at = datetime.fromisoformat(
                        json.loads(session_raw)["session_expires_at"]
                    )
                except (ValueError, KeyError, TypeError):
                    pipe.unwatch()
                    return None
                if now >= session_expires_at:
                    pipe.unwatch()
                    return None
                access_expires_at = min(
                    now + timedelta(seconds=self._settings.access_ttl_seconds),
                    session_expires_at,
                )
                refresh_expires_at = session_expires_at
                chain["refresh_expires_at"] = refresh_expires_at.isoformat()
                pipe.multi()
                pipe.sadd(_chains_key(sid), cid)
                pipe.pexpireat(_chains_key(sid), _millis(session_expires_at))
                pipe.set(
                    _chain_key(sid, cid),
                    json.dumps(chain),
                    pxat=_millis(session_expires_at),
                )
                pipe.set(
                    _refresh_key(token_hash),
                    f"{sid}:{cid}",
                    pxat=_millis(session_expires_at),
                )
                pipe.execute()
                return self._grant(
                    user_id,
                    sid,
                    cid,
                    token,
                    access_expires_at,
                    refresh_expires_at,
                    session_expires_at,
                    now,
                )
            except redis.WatchError:
                continue
            finally:
                pipe.reset()
        raise AuthUnavailable

    def _grant(
        self,
        user_id: UUID,
        sid: str,
        cid: str,
        refresh_token: str,
        access_expires_at: datetime,
        refresh_expires_at: datetime,
        session_expires_at: datetime,
        now: datetime,
    ) -> SessionGrant:
        return SessionGrant(
            sid=sid,
            cid=cid,
            session_token=create_token(
                user_id,
                sid,
                self._settings,
                cid=cid,
                expires_at=access_expires_at,
                issued_at=now,
            ),
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            session_expires_at=session_expires_at,
        )

    async def rotate(
        self,
        refresh_token: str,
        *,
        expected_sid: str | None = None,
        expected_cid: str | None = None,
    ) -> SessionGrant:
        token_hash = _hash_token(refresh_token)

        def _rotate() -> SessionGrant:
            try:
                for _ in range(self._settings.max_rotate_attempts):
                    try:
                        return self._rotate_once(token_hash, expected_sid, expected_cid)
                    except redis.WatchError:
                        continue
            except redis.RedisError as exc:
                raise AuthUnavailable from exc
            raise AuthUnavailable

        return await asyncio.to_thread(_rotate)

    def _rotate_once(
        self, token_hash: str, expected_sid: str | None, expected_cid: str | None
    ) -> SessionGrant:
        identity = _decode(self._client.get(_refresh_key(token_hash)))
        if not identity or ":" not in identity:
            raise RefreshInvalid
        sid, cid = identity.split(":", 1)
        if (expected_sid is not None and sid != expected_sid) or (
            expected_cid is not None and cid != expected_cid
        ):
            raise RefreshInvalid

        chain_key = _chain_key(sid, cid)
        pipe = self._client.pipeline()
        try:
            pipe.watch(chain_key)
            raw = pipe.get(chain_key)
            if raw is None:
                raise RefreshInvalid
            try:
                chain = json.loads(raw)
                now = self._clock()
                current_hash = chain["refresh_hash"]
                prev_hash = chain.get("prev_refresh_hash")
                refresh_expiry = datetime.fromisoformat(chain["refresh_expires_at"])
            except (ValueError, KeyError, TypeError):
                raise RefreshInvalid from None

            session_raw = self._client.get(_session_key(sid))
            if session_raw is None:
                raise RefreshInvalid
            try:
                session = json.loads(session_raw)
                session_expiry = datetime.fromisoformat(session["session_expires_at"])
            except (ValueError, KeyError, TypeError):
                raise RefreshInvalid from None
            if now >= session_expiry:
                raise RefreshInvalid
            if token_hash == current_hash:
                if now >= refresh_expiry:
                    raise RefreshInvalid
            elif token_hash == prev_hash:
                rotated_at = datetime.fromisoformat(chain["rotated_at"])
                if now - rotated_at > timedelta(
                    seconds=self._settings.refresh_grace_seconds
                ):
                    self._revoke_reused_chain(sid, cid, current_hash, prev_hash)
                    raise RefreshReuseDetected
            else:
                raise RefreshInvalid

            new_token = secrets.token_urlsafe(32)
            new_hash = _hash_token(new_token)
            access_expiry = min(
                now + timedelta(seconds=self._settings.access_ttl_seconds),
                session_expiry,
            )
            new_refresh_expiry = session_expiry
            updated = json.dumps(
                {
                    "refresh_hash": new_hash,
                    "prev_refresh_hash": current_hash,
                    "refresh_expires_at": new_refresh_expiry.isoformat(),
                    "rotated_at": now.isoformat(),
                }
            )
            pipe.multi()
            pipe.set(
                chain_key,
                updated,
                pxat=_millis(session_expiry),
            )
            pipe.set(
                _refresh_key(new_hash),
                f"{sid}:{cid}",
                pxat=_millis(session_expiry),
            )
            pipe.pexpireat(
                _refresh_key(current_hash),
                _millis(session_expiry),
            )
            if prev_hash and prev_hash not in (new_hash, current_hash):
                pipe.delete(_refresh_key(prev_hash))
            pipe.execute()
            return self._grant(
                UUID(session["user_id"]),
                sid,
                cid,
                new_token,
                access_expiry,
                new_refresh_expiry,
                session_expiry,
                now,
            )
        finally:
            pipe.reset()

    def _revoke_reused_chain(
        self, sid: str, cid: str, current_hash: str, previous_hash: str | None
    ) -> None:
        pipe = self._client.pipeline()
        try:
            pipe.watch(_chains_key(sid), _chain_key(sid, cid))
            raw = pipe.get(_chain_key(sid, cid))
            if raw is None:
                pipe.unwatch()
                return
            latest = json.loads(raw)
            latest_current = latest.get("refresh_hash")
            latest_previous = latest.get("prev_refresh_hash")
            if latest_previous != previous_hash or latest_current != current_hash:
                pipe.unwatch()
                raise redis.WatchError
            pipe.multi()
            pipe.delete(_chain_key(sid, cid), _ws_key(sid, cid))
            pipe.delete(_refresh_key(current_hash))
            if previous_hash:
                pipe.delete(_refresh_key(previous_hash))
            pipe.srem(_chains_key(sid), cid)
            pipe.execute()
        finally:
            pipe.reset()

    async def get_session(self, sid: str, cid: str | None = None) -> AuthSession | None:
        def _get() -> AuthSession | None:
            try:
                values = self._client.mget(
                    [
                        _session_key(sid),
                        *([_chain_key(sid, cid)] if cid is not None else []),
                    ]
                )
            except redis.RedisError as exc:
                raise AuthUnavailable from exc
            if not values[0] or (cid is not None and not values[1]):
                return None
            try:
                data = json.loads(values[0])
                return AuthSession(
                    UUID(data["user_id"]), UUID(data["facility_id"]), sid
                )
            except (ValueError, KeyError, TypeError):
                return None

        return await asyncio.to_thread(_get)

    async def claim_ws(self, sid: str, cid: str, connection_id: str) -> bool:
        def _claim() -> bool:
            try:
                for _ in range(self._settings.max_rotate_attempts):
                    pipe = self._client.pipeline()
                    try:
                        pipe.watch(_chain_key(sid, cid), _session_key(sid))
                        chain_raw, session_raw = pipe.mget(
                            _chain_key(sid, cid), _session_key(sid)
                        )
                        if not chain_raw or not session_raw:
                            return False
                        expiry = datetime.fromisoformat(
                            json.loads(session_raw)["session_expires_at"]
                        )
                        pipe.multi()
                        pipe.set(_ws_key(sid, cid), connection_id, pxat=_millis(expiry))
                        pipe.execute()
                        return True
                    except redis.WatchError:
                        continue
                    finally:
                        pipe.reset()
                raise AuthUnavailable
            except redis.RedisError as exc:
                raise AuthUnavailable from exc

        return await asyncio.to_thread(_claim)

    async def owns_ws(self, sid: str, cid: str, connection_id: str) -> bool:
        def _owns() -> bool:
            try:
                chain, owner = self._client.mget(
                    _chain_key(sid, cid), _ws_key(sid, cid)
                )
            except redis.RedisError as exc:
                raise AuthUnavailable from exc
            return bool(chain and _decode(owner) == connection_id)

        return await asyncio.to_thread(_owns)

    async def chain_expiries(
        self, sid: str, cid: str
    ) -> tuple[datetime, datetime] | None:
        def _read() -> tuple[datetime, datetime] | None:
            try:
                session_raw, chain_raw = self._client.mget(
                    _session_key(sid), _chain_key(sid, cid)
                )
            except redis.RedisError as exc:
                raise AuthUnavailable from exc
            if not session_raw or not chain_raw:
                return None
            try:
                session_expiry = datetime.fromisoformat(
                    json.loads(session_raw)["session_expires_at"]
                )
                refresh_expiry = datetime.fromisoformat(
                    json.loads(chain_raw)["refresh_expires_at"]
                )
                return session_expiry, refresh_expiry
            except (ValueError, TypeError, KeyError):
                return None

        return await asyncio.to_thread(_read)

    async def destroy_chain(self, user_id: UUID, sid: str, cid: str) -> None:
        await asyncio.to_thread(self._destroy_chain, user_id, sid, cid)

    def _destroy_chain(self, user_id: UUID, sid: str, cid: str) -> None:
        try:
            for _ in range(self._settings.max_rotate_attempts):
                pipe = self._client.pipeline()
                try:
                    pipe.watch(
                        _chains_key(sid), _chain_key(sid, cid), _user_sid_key(user_id)
                    )
                    chain_ids = pipe.smembers(_chains_key(sid))
                    indexed_sid = _decode(pipe.get(_user_sid_key(user_id)))
                    chain_members = [
                        value
                        for value in (_decode(item) for item in chain_ids)
                        if value
                    ]
                    if chain_members:
                        pipe.watch(*(_chain_key(sid, value) for value in chain_members))
                    live_ids = [
                        _decode(value)
                        for value in chain_ids
                        if self._client.exists(_chain_key(sid, _decode(value) or ""))
                    ]
                    live_ids = [value for value in live_ids if value]
                    remaining_ids = [value for value in live_ids if value != cid]
                    chain_raw = self._client.get(_chain_key(sid, cid))
                    hashes: set[str] = set()
                    if chain_raw:
                        chain = json.loads(chain_raw)
                        hashes = {
                            chain.get("refresh_hash"),
                            chain.get("prev_refresh_hash"),
                        } - {None}
                    pipe.multi()
                    pipe.delete(_chain_key(sid, cid), _ws_key(sid, cid))
                    for token_hash in hashes:
                        pipe.delete(_refresh_key(token_hash))
                    pipe.srem(_chains_key(sid), cid)
                    dead_ids = {_decode(value) for value in chain_ids} - set(live_ids)
                    dead_ids.discard(None)
                    if dead_ids:
                        pipe.srem(_chains_key(sid), *dead_ids)
                    if not remaining_ids:
                        pipe.delete(_session_key(sid), _chains_key(sid))
                        if indexed_sid == sid:
                            pipe.delete(_user_sid_key(user_id))
                    pipe.execute()
                    return
                except redis.WatchError:
                    continue
                finally:
                    pipe.reset()
            raise AuthUnavailable
        except redis.RedisError as exc:
            raise AuthUnavailable from exc

    async def destroy_legacy_session(self, user_id: UUID, sid: str) -> None:
        def _destroy() -> None:
            try:
                for _ in range(self._settings.max_rotate_attempts):
                    pipe = self._client.pipeline()
                    try:
                        pipe.watch(
                            _session_key(sid),
                            _user_sid_key(user_id),
                            _chains_key(sid),
                        )
                        chain_ids = pipe.smembers(_chains_key(sid))
                        indexed_sid = _decode(pipe.get(_user_sid_key(user_id)))
                        cids = [
                            cid
                            for cid in (_decode(value) for value in chain_ids)
                            if cid
                        ]
                        if cids:
                            pipe.watch(*(_chain_key(sid, cid) for cid in cids))
                        chain_values = {
                            cid: self._client.get(_chain_key(sid, cid)) for cid in cids
                        }
                        pipe.multi()
                        pipe.delete(_session_key(sid), _chains_key(sid))
                        if indexed_sid == sid:
                            pipe.delete(_user_sid_key(user_id))
                        for cid in cids:
                            raw = chain_values[cid]
                            if raw:
                                try:
                                    chain = json.loads(raw)
                                except (ValueError, TypeError):
                                    chain = {}
                                for token_hash in (
                                    chain.get("refresh_hash"),
                                    chain.get("prev_refresh_hash"),
                                ):
                                    if token_hash:
                                        pipe.delete(_refresh_key(token_hash))
                            pipe.delete(_chain_key(sid, cid), _ws_key(sid, cid))
                        pipe.execute()
                        return
                    except redis.WatchError:
                        continue
                    finally:
                        pipe.reset()
                raise AuthUnavailable
            except redis.RedisError as exc:
                raise AuthUnavailable from exc

        await asyncio.to_thread(_destroy)


__all__ = [
    "AuthSession",
    "AuthUnavailable",
    "RefreshInvalid",
    "RefreshReuseDetected",
    "SessionGrant",
    "SessionStore",
]
