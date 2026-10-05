import json
import logging
from collections.abc import Iterable

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
        except Exception as exc:  # noqa: BLE001 - best-effort cache; never raise
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
        except Exception as exc:  # noqa: BLE001 - best-effort cache; never raise
            logger.warning(
                "Redis metrics cache unavailable during set key=%s error=%s",
                key,
                type(exc).__name__,
            )

    def delete_many(self, keys: Iterable[str]) -> None:
        key_list = list(keys)
        if not key_list:
            return
        try:
            self.client.delete(*key_list)
        except Exception as exc:  # noqa: BLE001 - best-effort cache; never raise
            logger.warning(
                "Redis metrics cache unavailable during delete keys=%s error=%s",
                len(key_list),
                type(exc).__name__,
            )

    def scan_keys(self, prefix: str) -> list[str]:
        try:
            return [
                key.decode() if isinstance(key, bytes) else str(key)
                for key in self.client.scan_iter(match=f"{prefix}*")
            ]
        except Exception as exc:  # noqa: BLE001 - best-effort cache; never raise
            logger.warning(
                "Redis metrics cache unavailable during scan prefix=%s error=%s",
                prefix,
                type(exc).__name__,
            )
            return []


__all__ = ["MetricsCache"]
