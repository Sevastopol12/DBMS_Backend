import asyncio
import json
from dataclasses import dataclass
from uuid import UUID

import redis

from backend.api.auth.settings import AuthSettings


class AuthUnavailable(Exception):
    """Raised when Redis is unavailable or times out."""


@dataclass(frozen=True)
class AuthSession:
    user_id: UUID
    facility_id: UUID
    sid: str


class SessionStore:
    def __init__(self, client: redis.Redis, settings: AuthSettings) -> None:
        self._client = client
        self._settings = settings

    async def create_session(self, user_id: UUID, facility_id: UUID, sid: str) -> None:
        def _create() -> None:
            try:
                session_key = f"auth:session:{sid}"
                user_key = f"auth:user_sessions:{user_id}"
                data = json.dumps(
                    {"user_id": str(user_id), "facility_id": str(facility_id)}
                )

                pipe = self._client.pipeline()
                pipe.set(session_key, data, ex=self._settings.session_ttl_seconds)
                pipe.sadd(user_key, sid)
                pipe.execute()
            except redis.RedisError as e:
                raise AuthUnavailable from e

        await asyncio.to_thread(_create)

    async def get_session(self, sid: str) -> AuthSession | None:
        def _get() -> str | None:
            try:
                return self._client.get(f"auth:session:{sid}")
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
                session_key = f"auth:session:{sid}"
                user_key = f"auth:user_sessions:{user_id}"

                pipe = self._client.pipeline()
                pipe.delete(session_key)
                pipe.srem(user_key, sid)
                pipe.execute()
            except redis.RedisError as e:
                raise AuthUnavailable from e

        await asyncio.to_thread(_destroy)
