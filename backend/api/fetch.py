from fastapi import APIRouter, Depends, status
from typing import Annotated

from backend.domain.models import MappingRequest, MappingResponse
from backend.api.dependencies import get_redis_cache
from backend.redis import RedisCache
from dotenv import load_dotenv

load_dotenv()

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
