import asyncio
import os

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class RDBAsyncConnectionConfig:
    async_engine: AsyncEngine
    async_session_local: async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class PoolSettings:
    pool_size: int
    max_overflow: int
    pool_timeout: float
    pool_recycle: int
    pre_ping: bool


def api_pool_settings() -> PoolSettings:
    return PoolSettings(
        pool_size=int(os.getenv("API_DB_POOL_SIZE", "3")),
        max_overflow=int(os.getenv("API_DB_MAX_OVERFLOW", "2")),
        pool_timeout=30,
        pool_recycle=1800,
        pre_ping=True,
    )


def task_pool_settings() -> PoolSettings:
    return PoolSettings(
        pool_size=int(os.getenv("TASK_DB_POOL_SIZE", "1")),
        max_overflow=int(os.getenv("TASK_DB_MAX_OVERFLOW", "0")),
        pool_timeout=10,
        pool_recycle=-1,
        pre_ping=False,
    )


def create_connection(
    db_level: str, *, pool: PoolSettings | None = None, app_name: str | None = None
) -> RDBAsyncConnectionConfig:
    engine_kwargs = {}
    if pool is not None:
        engine_kwargs.update(
            pool_size=pool.pool_size,
            max_overflow=pool.max_overflow,
            pool_timeout=pool.pool_timeout,
            pool_recycle=pool.pool_recycle,
            pool_pre_ping=pool.pre_ping,
        )
    if app_name is not None:
        engine_kwargs["connect_args"] = {
            "server_settings": {"application_name": app_name}
        }

    async_engine: AsyncEngine = create_async_engine(
        url=os.getenv(f"{db_level.upper()}_RDB_URL"), **engine_kwargs
    )
    async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=async_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    return RDBAsyncConnectionConfig(async_engine, async_session)


async def probe_connection(
    config: RDBAsyncConnectionConfig, *, timeout: float = 10.0
) -> None:
    async def _probe() -> None:
        async with config.async_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    await asyncio.wait_for(_probe(), timeout=timeout)


async def dispose_connection(config: RDBAsyncConnectionConfig) -> None:
    await config.async_engine.dispose()
