import json
import logging

from redis import Redis

logger = logging.getLogger(__name__)


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


class MetricsCache:
    def __init__(self, cache_client: Redis):
        self.client = cache_client

    def get(self, key: str) -> object | None:
        try:
            value = self.client.get(key)
            return None if value is None else json.loads(
                value, parse_constant=_reject_nonstandard_constant
            )
        except Exception as exc:
            logger.warning(
                "Redis metrics cache unavailable during get key=%s error=%s",
                key,
                type(exc).__name__,
            )
            return None

    def set(
        self,
        key: str,
        value: object,
        ttl_seconds: int | None = None,
    ) -> None:
        try:
            serialized = json.dumps(value, default=str, allow_nan=False)
            if ttl_seconds is None:
                self.client.set(key, serialized)
            else:
                self.client.set(key, serialized, ex=ttl_seconds)
        except Exception as exc:
            logger.warning(
                "Redis metrics cache unavailable during set key=%s error=%s",
                key,
                type(exc).__name__,
            )


__all__ = ["MetricsCache"]
