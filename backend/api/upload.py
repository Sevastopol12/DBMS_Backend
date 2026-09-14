import logging

from fastapi import APIRouter
from fastapi import Depends, status
from typing import Annotated
from fastapi.exceptions import HTTPException
from sqlalchemy.orm.exc import DetachedInstanceError

from backend.database import get_staging_repository, get_staging_storage
from backend.database.service import (
    IngestionRepository,
    StorageService,
    IngestionService,
)
from backend.database.errors import DuplicatedContentError
from backend.domain.models import IngestionCreate, IngestionResponse, IngestionComplete
from backend.celery import transform


logger = logging.getLogger(__name__)

router = APIRouter()

IngestionRepositoryService = Annotated[
    IngestionRepository, Depends(get_staging_repository)
]
FileStorageService = Annotated[StorageService, Depends(get_staging_storage)]


def get_ingestion_service(
    staging_repository_service: IngestionRepositoryService,
    storage_service: FileStorageService,
):
    return IngestionService(staging_repository_service, storage_service)


Ingestion = Annotated[IngestionService, Depends(get_ingestion_service)]


@router.post(
    "/ingestions",
    response_model=IngestionResponse,
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
    except DetachedInstanceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.post(
    "/{file}/complete",
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

    transform.delay(response.id)
    return response
