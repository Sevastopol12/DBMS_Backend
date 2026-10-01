import os

import redis


def create_redis_pool() -> redis.ConnectionPool:
    return redis.ConnectionPool(
        host=os.getenv("CACHE_HOST"),
        port=os.getenv("CACHE_PORT"),
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


__all__ = ["close_redis", "create_redis_client", "create_redis_pool"]
