import os

from .connection import create_connection
from .mapping.repository import HeaderMappingRepository, HeaderMappingRow


async def load_header_mappings() -> tuple[HeaderMappingRow, ...]:
    if not os.getenv("MAPPING_RDB_URL"):
        raise RuntimeError("MAPPING_RDB_URL is required to load header mappings")

    config = create_connection("mapping")
    try:
        return await HeaderMappingRepository(config).load_active()
    finally:
        await config.async_engine.dispose()


__all__ = [
    "load_header_mappings",
    "HeaderMappingRepository",
    "HeaderMappingRow",
]
