from fastapi import Depends, Request

from backend.api.metrics_service import MetricsService
from backend.api.resources import ApiResources
from backend.database.service import IngestionRepository, StorageService
from backend.database.service.metrics.repository import MetricsRepository
from backend.domain.processing.mapping.legacy.legacy_cache import MappingCache
from backend.redis_cache.cache import MetricsCache


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


def get_mapping_cache(res: ApiResources = Depends(get_resources)) -> MappingCache:
    return MappingCache(res.redis)


def get_metrics_cache(res: ApiResources = Depends(get_resources)) -> MetricsCache:
    return MetricsCache(res.redis)


def get_metrics_repository(
    res: ApiResources = Depends(get_resources),
) -> MetricsRepository:
    return MetricsRepository(config=res.application)


def get_metrics_service(
    cache: MetricsCache = Depends(get_metrics_cache),
    repository: MetricsRepository = Depends(get_metrics_repository),
) -> MetricsService:
    return MetricsService(cache=cache, repository=repository)


__all__ = [
    "get_resources",
    "get_ingestion_repository",
    "get_storage_service",
    "get_mapping_cache",
    "get_metrics_cache",
    "get_metrics_repository",
    "get_metrics_service",
]
