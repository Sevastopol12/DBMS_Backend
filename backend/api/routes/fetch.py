from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.exceptions import HTTPException

from backend.api.auth.dependencies import require_session
from backend.api.auth.sessions import AuthSession
from backend.api.dependencies import (
    get_ingestion_repository,
    get_mapping_cache,
    get_storage_service,
)
from backend.api.dto import (
    FileDetailResponse,
    RejectionDownloadResponse,
    _serialize_file_detail,
)
from backend.database.service import IngestionRepository, StorageService
from backend.database.service.storage import presigned_get_ttl_from_env
from backend.domain.processing.mapping.legacy.legacy_cache import (
    MappingCache,
    MappingRequest,
    MappingResponse,
)
from backend.timezone import now_vietnam

router = APIRouter(dependencies=[Depends(require_session)])

ApplicationCache = Annotated[MappingCache, Depends(get_mapping_cache)]
Session = Annotated[AuthSession, Depends(require_session)]
IngestionRepositoryDep = Annotated[
    IngestionRepository, Depends(get_ingestion_repository)
]
StorageDep = Annotated[StorageService, Depends(get_storage_service)]


@router.get("/files", response_model=list[FileDetailResponse])
async def list_files(
    session: Session,
    repository: IngestionRepositoryDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[str | None, Query()] = None,
) -> list[FileDetailResponse]:
    rows = await repository.list_for_facility(
        session.facility_id, status=status, limit=limit, offset=offset
    )
    return [_serialize_file_detail(row) for row in rows]


@router.get("/files/{file_id}", response_model=FileDetailResponse)
async def get_file(
    file_id: UUID, session: Session, repository: IngestionRepositoryDep
) -> FileDetailResponse:
    row = await repository.get_for_facility(file_id, session.facility_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )
    return _serialize_file_detail(row)


@router.get("/files/{file_id}/rejections", response_model=RejectionDownloadResponse)
async def download_rejections(
    file_id: UUID,
    session: Session,
    repository: IngestionRepositoryDep,
    storage: StorageDep,
) -> RejectionDownloadResponse:
    row = await repository.get_for_facility(file_id, session.facility_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )
    key = getattr(row, "rejection_artifact_key", None)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No rejection artifact"
        )
    expires_at = getattr(row, "rejection_artifact_expires_at", None)
    if expires_at is not None and now_vietnam() > expires_at:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="Rejection artifact expired"
        )
    ttl = presigned_get_ttl_from_env()
    url = storage.presign_get(key, ttl_seconds=ttl, download_filename=row.filename)
    return RejectionDownloadResponse(
        url=url, expires_in_seconds=ttl, filename=row.filename or f"{file_id}.xlsx"
    )


@router.post(
    "/mapping/{filename}",
    status_code=status.HTTP_200_OK,
    response_model=MappingResponse,
)
async def get_mapping_hint(
    request: MappingRequest, cache: ApplicationCache, session: Session
) -> MappingResponse:
    _ = session
    result = cache.get_mapping_hint(request)
    return result
