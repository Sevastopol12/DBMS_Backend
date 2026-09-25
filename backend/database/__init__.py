from .service import HeaderMappingRepository, HeaderMappingRow
from .connection import create_connection


async def load_header_mappings() -> tuple[HeaderMappingRow, ...]:
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
