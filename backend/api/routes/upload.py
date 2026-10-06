from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import DetachedInstanceError

from backend.api.auth.dependencies import require_session
from backend.api.auth.sessions import AuthSession
from backend.api.dependencies import get_ingestion_repository, get_storage_service
from backend.api.dto import (
    IngestionComplete,
    IngestionCreate,
    IngestionResponse,
    UploadReportCreate,
)
from backend.api.ingestion_service import (
    IngestionService,
    ParentArtifactExpiredError,
    ParentNotFoundError,
)
from backend.database.errors import (
    DuplicatedContentError,
    is_duplicate_content_integrity_error,
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
    response_model=IngestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload(
    request: IngestionCreate, ingestion_service: Ingestion, session: Session
) -> IngestionResponse:
    try:
        response: IngestionResponse = await ingestion_service.get_upload(
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


async def _complete(
    file_id: UUID, body: IngestionComplete, service: IngestionService, facility_id: UUID
) -> IngestionResponse:
    if file_id != body.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Path file id must equal body id",
        )
    try:
        response = await service.complete_upload(body, facility_id=facility_id)
    except DuplicatedContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Duplicated file"
        ) from exc
    except IntegrityError as exc:
        if is_duplicate_content_integrity_error(exc):
            raise HTTPException(
                status_code=409,
                detail="A file with this identical content already exists in the system.",
            ) from exc
        raise
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


@router.post(
    "/{file}/complete",
    response_model=IngestionResponse,
)
async def complete_upload(
    file: UUID,
    request: IngestionComplete,
    ingestion_service: Ingestion,
    session: Session,
):
    return await _complete(file, request, ingestion_service, session.facility_id)


@router.post(
    "/upload_report/",
    response_model=IngestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload_report(
    request: UploadReportCreate, ingestion_service: Ingestion, session: Session
) -> IngestionResponse:
    try:
        return await ingestion_service.create_upload_report(
            request, facility_id=session.facility_id
        )
    except ParentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Parent file not found"
        ) from exc
    except ParentArtifactExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="Parent artifact expired"
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post(
    "/upload_report/{file}/complete",
    response_model=IngestionResponse,
)
async def complete_upload_report(
    file: UUID,
    request: IngestionComplete,
    ingestion_service: Ingestion,
    session: Session,
):
    return await _complete(file, request, ingestion_service, session.facility_id)
