from fastapi import APIRouter, Depends, status
from typing import Annotated

from backend.domain.processing.mapping.legacy.legacy_cache import (
    MappingRequest,
    MappingResponse,
    RedisCache,
)
from backend.api.dependencies import get_redis_cache
router = APIRouter()

ApplicationCache = Annotated[RedisCache, Depends(get_redis_cache)]


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
