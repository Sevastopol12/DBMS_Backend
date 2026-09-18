import os
from collections.abc import Iterator
from redis import Redis
from dotenv import load_dotenv

from backend.domain.models import (
    MappingRequest,
    MappingResponse,
    HeaderMapValue,
    CacheSource,
)
from backend.domain.ingestion.normalization import normalize_header


load_dotenv()


class RedisCache:
    def __init__(self, cache_client: Redis):
        self.client = cache_client

    @staticmethod
    def _decode(value: object) -> str | None:
        """Convert Redis text responses to the domain's string contract."""
        if value is None:
            return None
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if isinstance(value, str):
            return value
        return None

    def get_column_cache(self, normalized_name: str) -> HeaderMapValue | None:
        """Return the cached target for one normalized source column, if one exists.

        Checks DIRECT_SOURCE first, then DYNAMIC_SOURCE.  Returns ``None``
        when neither cache has an entry for *normalized_name*.
        """
        result = self.client.hget(os.getenv("DIRECT_SOURCE"), normalized_name)
        if result:
            return HeaderMapValue(
                value=self._decode(result), cache_key=CacheSource.DIRECT
            )

        result = self.client.hget(os.getenv("DYNAMIC_SOURCE"), normalized_name)
        if result:
            return HeaderMapValue(
                value=self._decode(result), cache_key=CacheSource.DYNAMIC
            )

        return None

    def iter_mapping_keys(self) -> Iterator[str]:
        """Iterate source-column fields in the configured Redis hash.

        ``hscan_iter`` avoids loading a large mapping hash into memory and is
        the correct Redis operation for hash fields.  The fallback keeps this
        small abstraction usable with simple Redis test doubles.
        """
        for cache_name in [os.getenv("DIRECT_SOURCE"), os.getenv("DYNAMIC_SOURCE")]:
            if hasattr(self.client, "hscan_iter"):
                values = self.client.hscan_iter(cache_name)
            else:
                values = self.client.hkeys(cache_name)

            for value in values:
                decoded = self._decode(
                    value[0] if isinstance(value, (tuple, list)) else value
                )
                if decoded is not None:
                    yield decoded

    def get_mapping_hint(self, map_request: MappingRequest) -> MappingResponse:
        map_result = {
            col: self.get_column_cache(col) or normalize_header(col)
            for col in map_request.columns
        }

        return MappingResponse(filename=map_request.filename, mapping=map_result)


def get_application_cache() -> RedisCache:
    redis_client: Redis = Redis(
        host=os.getenv("CACHE_HOST"), port=os.getenv("CACHE_PORT")
    )
    return RedisCache(redis_client)


__all__ = ["get_application_cache", "RedisCache"]
