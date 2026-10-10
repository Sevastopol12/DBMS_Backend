from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.service.auth.schema import AppUser


class AuthRepository:
    def __init__(self, config: RDBAsyncConnectionConfig) -> None:
        self._sessions = config.async_session_local

    async def get_active_by_username(self, username: str) -> AppUser | None:
        async with self._sessions() as session:
            result = await session.execute(
                select(AppUser).where(
                    func.lower(AppUser.username) == username.lower(),
                    AppUser.is_active.is_(True),
                )
            )
            return result.scalars().first()

    async def touch_last_login(self, user_id: UUID) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(AppUser)
                .where(AppUser.id == user_id)
                .values(last_login_at=func.now())
            )
            await session.commit()
