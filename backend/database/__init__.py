import os

from .service import (
    HeaderMappingRepository,
    HeaderMappingRow,
    IngestionRepository,
    StorageService,
)
from .service.repository.production import ReportRepository
from .connection import create_connection, get_storage_config


def get_staging_repository() -> IngestionRepository:
    return IngestionRepository(config=create_connection("staging"))


def get_production_repository() -> ReportRepository:
    return ReportRepository(config=create_connection("application"))


def get_staging_storage() -> StorageService:
    return StorageService(config=get_storage_config())


async def load_header_mappings() -> tuple[HeaderMappingRow, ...]:
    if not os.getenv("MAPPING_RDB_URL"):
        raise RuntimeError("MAPPING_RDB_URL is required to load header mappings")

    config = create_connection("mapping")
    try:
        return await HeaderMappingRepository(config).load_active()
    finally:
        await config.async_engine.dispose()


__all__ = [
    "get_staging_repository",
    "get_staging_storage",
    "get_production_repository",
    "load_header_mappings",
    "HeaderMappingRepository",
    "HeaderMappingRow",
]
