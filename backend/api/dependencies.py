from typing import Annotated

from fastapi import Depends, Request

from backend.api.metrics_service import MetricsService
from backend.api.resources import ApiResources
from backend.database.service import IngestionRepository, StorageService
from backend.database.service.metrics.repository import MetricsRepository
from backend.database.service.production.repository import ReportRepository
from backend.database.service.staging.workflow_repository import WorkflowRunRepository
from backend.domain.processing.mapping.legacy.legacy_cache import MappingCache
from backend.redis_cache.cache import MetricsCache


def get_resources(request: Request) -> ApiResources:
    return request.app.state.resources


ResourcesDep = Annotated[ApiResources, Depends(get_resources)]


def get_ingestion_repository(
    res: ResourcesDep,
) -> IngestionRepository:
    return IngestionRepository(config=res.staging)


IngestionRepositoryDep = Annotated[
    IngestionRepository, Depends(get_ingestion_repository)
]


def get_storage_service(
    res: ResourcesDep,
) -> StorageService:
    return StorageService(config=res.storage)


StorageServiceDep = Annotated[StorageService, Depends(get_storage_service)]


def get_mapping_cache(res: ResourcesDep) -> MappingCache:
    return MappingCache(res.redis)


MappingCacheDep = Annotated[MappingCache, Depends(get_mapping_cache)]


def get_metrics_cache(res: ResourcesDep) -> MetricsCache:
    return MetricsCache(res.redis)


MetricsCacheDep = Annotated[MetricsCache, Depends(get_metrics_cache)]


def get_metrics_repository(
    res: ResourcesDep,
) -> MetricsRepository:
    return MetricsRepository(config=res.application)


MetricsRepositoryDep = Annotated[MetricsRepository, Depends(get_metrics_repository)]


def get_metrics_service(
    cache: MetricsCacheDep,
    repository: MetricsRepositoryDep,
) -> MetricsService:
    return MetricsService(cache=cache, repository=repository)


MetricsServiceDep = Annotated[MetricsService, Depends(get_metrics_service)]


def get_workflow_repository(
    res: ResourcesDep,
) -> WorkflowRunRepository:
    return WorkflowRunRepository(config=res.staging)


WorkflowRunRepositoryDep = Annotated[
    WorkflowRunRepository, Depends(get_workflow_repository)
]


def get_report_repository(
    res: ResourcesDep,
) -> ReportRepository:
    return ReportRepository(config=res.application)


ReportRepositoryDep = Annotated[ReportRepository, Depends(get_report_repository)]


__all__ = [
    "IngestionRepositoryDep",
    "MappingCacheDep",
    "MetricsCacheDep",
    "MetricsRepositoryDep",
    "MetricsServiceDep",
    "ReportRepositoryDep",
    "ResourcesDep",
    "StorageServiceDep",
    "WorkflowRunRepositoryDep",
    "get_ingestion_repository",
    "get_mapping_cache",
    "get_metrics_cache",
    "get_metrics_repository",
    "get_metrics_service",
    "get_report_repository",
    "get_resources",
    "get_storage_service",
    "get_workflow_repository",
]
