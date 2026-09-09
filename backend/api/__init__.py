from fastapi import APIRouter
import logging

from typing import Annotated
from uuid import UUID
from fastapi import Depends, status
from fastapi.exceptions import HTTPException

from backend.database import get_staging_rdb, get_staging_storage
from backend.database.service import RDBService, StorageService, IngestionService
from backend.database.schema import FileStatus
from backend.database.errors import DuplicatedContentError

from backend.domain.models import IngestionCreate, IngestionResponse, IngestionComplete

logger = logging.getLogger(__name__)

router = APIRouter()


RelationalDatabaseService = Annotated[RDBService, Depends(get_staging_rdb)]
FileStorageService = Annotated[StorageService, Depends(get_staging_storage)]


def get_ingestion_service(
    rdb_service: RelationalDatabaseService, storage_service: FileStorageService
):
    return IngestionService(rdb_service, storage_service)


Ingestion = Annotated[IngestionService, Depends(get_ingestion_service)]


@router.post(
    "/api/v1/ingestions",
    repsonse_model=IngestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload(
    request: IngestionCreate, ingestion_service: Ingestion
) -> IngestionResponse:
    try:
        response: IngestionResponse = await ingestion_service.get_upload(file=request)
        return response
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post(
    "/api/v1/{file}/complete",
    response_model=IngestionResponse,
)
async def complete_upload(request: IngestionComplete, ingestion_service: Ingestion):
    try:
        response: IngestionResponse = await ingestion_service.complete_upload(request)

    except DuplicatedContentError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Duplicated file"
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if response is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )

    return response
