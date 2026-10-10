from fastapi import APIRouter

from backend.api.data_objects.health import HealthStatusResponse

router = APIRouter()


@router.get("/health", response_model=HealthStatusResponse)
async def get_health() -> HealthStatusResponse:
    return HealthStatusResponse(status="ok")


__all__ = ["router"]
