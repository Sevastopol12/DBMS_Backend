import os

import redis
import redis.asyncio as async_redis


def create_redis_pool() -> redis.ConnectionPool:
    db_env = os.getenv("CACHE_DB")
    db = int(db_env) if db_env else 0
    ssl = os.getenv("CACHE_TLS", "off").lower() == "on"

    return redis.ConnectionPool(
        host=os.getenv("CACHE_HOST"),
        port=os.getenv("CACHE_PORT"),
        db=db,
        password=os.getenv("CACHE_PASSWORD"),
        connection_class=redis.SSLConnection if ssl else redis.Connection,
        max_connections=10,
        socket_connect_timeout=1.0,
        socket_timeout=2.0,
        health_check_interval=30,
    )


def create_redis_client(
    pool: redis.ConnectionPool | None = None,
) -> redis.Redis:
    if pool is None:
        pool = create_redis_pool()
    return redis.Redis(connection_pool=pool)


def close_redis(client: redis.Redis | None) -> None:
    if client is None:
        return

    client.close()
    pool = getattr(client, "connection_pool", None)
    if pool is not None:
        pool.disconnect()


def create_async_redis_client() -> async_redis.Redis:
    db_env = os.getenv("CACHE_DB")
    db = int(db_env) if db_env else 0
    ssl = os.getenv("CACHE_TLS", "off").lower() == "on"
    connection_class = async_redis.SSLConnection if ssl else async_redis.Connection
    pool = async_redis.ConnectionPool(
        host=os.getenv("CACHE_HOST"),
        port=int(os.getenv("CACHE_PORT", "6379")),
        db=db,
        password=os.getenv("CACHE_PASSWORD"),
        connection_class=connection_class,
        max_connections=10,
        socket_connect_timeout=1.0,
        socket_timeout=None,
        health_check_interval=30,
    )
    return async_redis.Redis(connection_pool=pool)


async def close_async_redis(client: async_redis.Redis | None) -> None:
    if client is not None:
        await client.aclose()


__all__ = [
    "close_async_redis",
    "close_redis",
    "create_async_redis_client",
    "create_redis_client",
    "create_redis_pool",
]
