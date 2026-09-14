import os
from redis import Redis
from dotenv import load_dotenv

from backend.domain.models import MappingRequest, MappingResponse
from backend.domain.ingestion.mapping import normalize_column_name

load_dotenv()


class RedisCache:
    def __init__(self, cache_client: Redis):
        self.client = cache_client

    def get_mapping(self, map_request: MappingRequest) -> MappingResponse:
        map_result = {
            col: self.client.hget(os.getenv("COLUMN_CACHE"), col)
            or normalize_column_name(col)
            for col in map_request.columns
        }

        return MappingResponse(filename=map_request.filename, mapping=map_result)


def get_application_cache() -> RedisCache:
    redis_client: Redis = Redis(
        host=os.getenv("CACHE_HOST"), port=os.getenv("CACHE_PORT")
    )
    return RedisCache(redis_client)


__all__ = ["get_application_cache"]
