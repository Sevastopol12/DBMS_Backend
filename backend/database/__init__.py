from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from .connection import create_connection

if TYPE_CHECKING:
    from .service.mapping.repository import HeaderMappingRepository, HeaderMappingRow


def __getattr__(name: str):
    if name in {"HeaderMappingRepository", "HeaderMappingRow"}:
        from .service.mapping.repository import (
            HeaderMappingRepository,
            HeaderMappingRow,
        )

        return {
            "HeaderMappingRepository": HeaderMappingRepository,
            "HeaderMappingRow": HeaderMappingRow,
        }[name]
    raise AttributeError(name)


async def load_header_mappings() -> tuple[HeaderMappingRow, ...]:
    if not os.getenv("MAPPING_RDB_URL"):
        raise RuntimeError("MAPPING_RDB_URL is required to load header mappings")

    config = create_connection("mapping")
    try:
        repository_type = getattr(sys.modules[__name__], "HeaderMappingRepository")
        return await repository_type(config).load_active()
    finally:
        await config.async_engine.dispose()


__all__ = [
    "load_header_mappings",
    "HeaderMappingRepository",
    "HeaderMappingRow",
]
