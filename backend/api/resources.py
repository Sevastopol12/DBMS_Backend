import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

import redis
from fastapi import FastAPI

from backend.database.connection import (
    RDBAsyncConnectionConfig,
    StorageAsyncConnectionConfig,
    api_pool_settings,
    close_storage,
    create_connection,
    dispose_connection,
    get_storage_config,
    probe_connection,
    probe_storage,
    storage_settings_from_env,
)
from backend.redis_cache.connection import (
    close_redis,
    create_redis_client,
    create_redis_pool,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiResources:
    staging: RDBAsyncConnectionConfig
    application: RDBAsyncConnectionConfig
    storage: StorageAsyncConnectionConfig
    redis: redis.Redis


@asynccontextmanager
async def api_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        staging = create_connection(
            "staging", pool=api_pool_settings(), app_name="dbms-api"
        )
        stack.push_async_callback(dispose_connection, staging)
        await probe_connection(staging)

        application = create_connection(
            "application", pool=api_pool_settings(), app_name="dbms-api"
        )
        stack.push_async_callback(dispose_connection, application)
        try:
            await probe_connection(application)
        except Exception as exc:
            logger.warning(
                "metrics database unavailable during API startup: %s",
                type(exc).__name__,
            )

        storage = get_storage_config(**storage_settings_from_env())
        stack.callback(close_storage, storage)
        await probe_storage(storage)

        pool = create_redis_pool()
        redis_client = create_redis_client(pool)
        stack.callback(close_redis, redis_client)

        try:
            redis_client.ping()
        except Exception as exc:
            logger.warning(
                "Redis cache unavailable during API startup: %s",
                type(exc).__name__,
            )

        app.state.resources = ApiResources(
            staging=staging,
            application=application,
            storage=storage,
            redis=redis_client,
        )
        yield


__all__ = ["ApiResources", "api_lifespan"]
