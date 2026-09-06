from .service import RDBService, StorageService
from .connection import create_connection, get_storage_config


def get_staging_rdb() -> RDBService:
    return RDBService(config=create_connection("staging"))


def get_production_rdb() -> RDBService:
    return RDBService(config=create_connection("production"))


def get_staging_storage() -> StorageService:
    return StorageService(config=get_storage_config())


__all__ = ["get_staging_rdb", "get_staging_storage", "get_production_rdb"]
