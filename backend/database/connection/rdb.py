import os

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncEngine,
)
from dataclasses import dataclass


from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class RDBAsyncConnectionConfig:
    async_engine: AsyncEngine
    async_session_local: AsyncSession


def create_connection(db_level: str) -> RDBAsyncConnectionConfig:
    async_engine: AsyncEngine = create_async_engine(
        url=os.getenv(f"{db_level.upper()}_RDB_URL")
    )
    async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=async_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    return RDBAsyncConnectionConfig(async_engine, async_session)
