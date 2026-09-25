from fastapi import Depends, Request

from backend.api.resources import ApiResources
from backend.database.service import IngestionRepository, StorageService
from backend.redis import RedisCache


def get_resources(request: Request) -> ApiResources:
    return request.app.state.resources


def get_ingestion_repository(
    res: ApiResources = Depends(get_resources),
) -> IngestionRepository:
    return IngestionRepository(config=res.staging)


def get_storage_service(
    res: ApiResources = Depends(get_resources),
) -> StorageService:
    return StorageService(config=res.storage)


def get_redis_cache(res: ApiResources = Depends(get_resources)) -> RedisCache:
    return RedisCache(res.redis)


__all__ = [
    "get_resources",
    "get_ingestion_repository",
    "get_storage_service",
    "get_redis_cache",
]
