from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_mapping_cache
from backend.domain.processing.mapping.legacy.legacy_cache import (
    MappingCache,
    MappingRequest,
    MappingResponse,
)

router = APIRouter()

ApplicationCache = Annotated[MappingCache, Depends(get_mapping_cache)]


@router.post(
    "/mapping/{filename}",
    status_code=status.HTTP_200_OK,
    response_model=MappingResponse,
)
async def get_mapping_hint(
    request: MappingRequest, cache: ApplicationCache
) -> MappingResponse:
    result = cache.get_mapping_hint(request)
    return result
