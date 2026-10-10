from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse

from backend.api.auth.dependencies import require_session
from backend.api.auth.sessions import AuthSession
from backend.api.dependencies import (
    get_ingestion_repository,
    get_mapping_cache,
    get_rejection_service,
)
from backend.api.dto import (
    FileDetailResponse,
    RejectedArtifactDownload,
    RejectedArtifactItem,
    RejectedArtifactListResponse,
    RejectionDownloadResponse,
    _serialize_file_detail,
)
from backend.api.rejection_service import (
    InvalidCursorError,
    RejectionExpiredError,
    RejectionNotFoundError,
    RejectionService,
    RejectionUnavailableError,
)
from backend.database.service import IngestionRepository
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
RejectionServiceDep = Annotated[RejectionService, Depends(get_rejection_service)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="rejection artifact not found",
    )


def _expired() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_410_GONE, detail="rejection artifact expired"
    )


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="store unavailable",
    )


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


@router.get("/rejections", response_model=RejectedArtifactListResponse)
async def list_rejections(
    session: Session,
    service: RejectionServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    state: Annotated[Literal["available", "expired"] | None, Query()] = None,
) -> RejectedArtifactListResponse:
    try:
        return await service.list_artifacts(
            facility_id=session.facility_id,
            limit=limit,
            cursor=cursor,
            state=state,
        )
    except InvalidCursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid cursor",
        ) from exc
    except RejectionUnavailableError as exc:
        raise _unavailable() from exc


@router.get("/rejections/{file_id}", response_model=RejectedArtifactItem)
async def get_rejection(
    file_id: UUID, session: Session, service: RejectionServiceDep
) -> RejectedArtifactItem:
    try:
        return await service.get_artifact(
            facility_id=session.facility_id, file_id=file_id
        )
    except RejectionNotFoundError as exc:
        raise _not_found() from exc
    except RejectionUnavailableError as exc:
        raise _unavailable() from exc


@router.get("/rejections/{file_id}/download", response_model=RejectedArtifactDownload)
async def download_rejection_artifact(
    file_id: UUID,
    session: Session,
    service: RejectionServiceDep,
    redirect: Annotated[bool, Query()] = False,
) -> RejectedArtifactDownload | RedirectResponse:
    try:
        result = await service.download_artifact(
            facility_id=session.facility_id, file_id=file_id
        )
    except RejectionNotFoundError as exc:
        raise _not_found() from exc
    except RejectionExpiredError as exc:
        raise _expired() from exc
    except RejectionUnavailableError as exc:
        raise _unavailable() from exc
    if redirect:
        return RedirectResponse(result.download_url, status_code=status.HTTP_302_FOUND)
    return result


@router.get(
    "/files/{file_id}/rejections",
    response_model=RejectionDownloadResponse,
)
async def download_rejections(
    file_id: UUID, session: Session, service: RejectionServiceDep
) -> RejectionDownloadResponse:
    try:
        result = await service.download_artifact(
            facility_id=session.facility_id, file_id=file_id
        )
    except RejectionNotFoundError as exc:
        raise _not_found() from exc
    except RejectionExpiredError as exc:
        raise _expired() from exc
    except RejectionUnavailableError as exc:
        raise _unavailable() from exc
    return RejectionDownloadResponse(
        url=result.download_url,
        expires_in_seconds=max(
            0, int((result.url_expires_at - now_vietnam()).total_seconds())
        ),
        filename=result.artifact_filename,
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
