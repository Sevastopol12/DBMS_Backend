from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.orm.exc import DetachedInstanceError

from backend.api.auth.dependencies import require_session
from backend.api.auth.sessions import AuthSession
from backend.api.data_objects.ingestion import (
    CompleteUploadCreate,
    CompleteUploadResponse,
    RequestPresignedCreate,
    RequestPresignedResponse,
)
from backend.api.dependencies import get_ingestion_repository, get_storage_service
from backend.api.services.ingestion import (
    IngestionService,
)
from backend.database.errors import (
    FileObjectNotFound,
)
from backend.database.service import IngestionRepository, StorageService
from backend.worker.tasks.transform import transform

router = APIRouter(dependencies=[Depends(require_session)])

IngestionRepositoryService = Annotated[
    IngestionRepository, Depends(get_ingestion_repository)
]
FileStorageService = Annotated[StorageService, Depends(get_storage_service)]
Session = Annotated[AuthSession, Depends(require_session)]


def get_ingestion_service(
    staging_repository_service: IngestionRepositoryService,
    storage_service: FileStorageService,
):
    return IngestionService(staging_repository_service, storage_service)


Ingestion = Annotated[IngestionService, Depends(get_ingestion_service)]


@router.post(
    "/ingestions",
    response_model=RequestPresignedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload(
    request: RequestPresignedCreate, ingestion_service: Ingestion, session: Session
) -> RequestPresignedResponse:
    try:
        response: RequestPresignedResponse = await ingestion_service.get_upload(
            file=request, facility_id=session.facility_id
        )
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
    response_model=CompleteUploadResponse,
)
async def complete_upload(
    request: CompleteUploadCreate,
    service: Ingestion,
    session: Session,
) -> CompleteUploadResponse:
    try:
        response = await service.complete_upload(
            request, facility_id=session.facility_id
        )
    except FileObjectNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    if response is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )

    transform.delay(response.file_id)
    return response
