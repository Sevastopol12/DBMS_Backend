import logging
import os

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator

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


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiResources:
    staging: RDBAsyncConnectionConfig
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

        storage = get_storage_config(**storage_settings_from_env())
        stack.callback(close_storage, storage)
        await probe_storage(storage)

        pool = redis.ConnectionPool(
            host=os.getenv("CACHE_HOST"),
            port=os.getenv("CACHE_PORT"),
            max_connections=10,
            socket_connect_timeout=1.0,
            socket_timeout=2.0,
            health_check_interval=30,
        )
        stack.callback(pool.disconnect)
        redis_client = redis.Redis(connection_pool=pool)

        try:
            redis_client.ping()
        except Exception as exc:
            logger.warning("Redis cache unavailable during API startup: %s", exc)

        app.state.resources = ApiResources(
            staging=staging,
            storage=storage,
            redis=redis_client,
        )
        yield


__all__ = ["ApiResources", "api_lifespan"]
