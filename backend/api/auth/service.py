from uuid import UUID

import redis

from backend.api.auth.passwords import DUMMY_HASH, verify_password
from backend.api.auth.ratelimit import RateLimiter
from backend.api.auth.sessions import AuthUnavailable, SessionStore
from backend.api.auth.settings import AuthSettings
from backend.api.data_objects.auth import LoginResponse
from backend.database.service.auth.repository import AuthRepository


class AuthenticationFailed(Exception):
    pass


class AuthService:
    def __init__(
        self,
        settings: AuthSettings,
        session_store: SessionStore,
        rate_limiter: RateLimiter,
        repository: AuthRepository,
    ) -> None:
        self._settings = settings
        self._session_store = session_store
        self._rate_limiter = rate_limiter
        self._repository = repository

    async def login(self, username: str, password: str, ip: str) -> LoginResponse:
        try:
            await self._rate_limiter.check_and_increment(username, ip)
        except redis.RedisError as e:
            raise AuthUnavailable from e

        user = await self._repository.get_active_by_username(username)
        if user is None:
            # Dummy verify for timing parity
            await verify_password(DUMMY_HASH, password)
            raise AuthenticationFailed()

        is_valid = await verify_password(user.password_hash, password)
        if not is_valid:
            raise AuthenticationFailed()

        try:
            await self._rate_limiter.clear_user_bucket(username, ip)
        except redis.RedisError as e:
            raise AuthUnavailable from e

        grant = await self._session_store.login_session(user.id, user.facility_id)
        await self._repository.touch_last_login(user.id)

        return LoginResponse(
            session_token=grant.session_token,
            refresh_token=grant.refresh_token,
            facility_id=user.facility_id,
            access_expires_at=grant.access_expires_at,
            refresh_expires_at=grant.refresh_expires_at,
            session_expires_at=grant.session_expires_at,
        )

    async def logout(self, user_id: UUID, sid: str, cid: str | None) -> None:
        if cid is None:
            await self._session_store.destroy_legacy_session(user_id, sid)
        else:
            await self._session_store.destroy_chain(user_id, sid, cid)
