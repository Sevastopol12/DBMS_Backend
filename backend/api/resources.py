import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

import redis
import redis.asyncio as async_redis
from fastapi import FastAPI

from backend.api.realtime.hub import RealtimeHub
from backend.api.realtime.subscriber import run_metrics_subscriber
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
    close_async_redis,
    close_redis,
    create_async_redis_client,
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
    pubsub_redis: async_redis.Redis | None = None


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
            async with application.async_engine.connect() as conn:
                from sqlalchemy import text

                result = await conn.execute(
                    text("SELECT to_regclass('\"Auth\".app_user')")
                )
                if result.scalar_one_or_none() is None:
                    raise RuntimeError("Missing required table: Auth.app_user")
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001 - startup probe: metrics db fails open
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
        except Exception as exc:  # noqa: BLE001 - startup probe: redis cache fails open
            logger.warning(
                "Redis cache unavailable during API startup: %s",
                type(exc).__name__,
            )

        pubsub_redis = create_async_redis_client()
        stack.push_async_callback(close_async_redis, pubsub_redis)
        hub = RealtimeHub()
        subscriber_task = asyncio.create_task(
            run_metrics_subscriber(pubsub_redis, hub), name="metrics-subscriber"
        )

        async def stop_realtime() -> None:
            subscriber_task.cancel()
            await asyncio.gather(subscriber_task, return_exceptions=True)
            await hub.close_all(1001)

        stack.push_async_callback(stop_realtime)

        app.state.resources = ApiResources(
            staging=staging,
            application=application,
            storage=storage,
            redis=redis_client,
            pubsub_redis=pubsub_redis,
        )
        app.state.hub = hub

        yield


__all__ = ["ApiResources", "api_lifespan"]
