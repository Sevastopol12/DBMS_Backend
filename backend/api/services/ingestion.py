from uuid import UUID, uuid4

from backend.api.data_objects.ingestion import (
    CompleteUploadCreate,
    CompleteUploadResponse,
    RequestPresignedCreate,
    RequestPresignedResponse,
    _get_safe_filename,
    _serialize_complete_response,
)
from backend.database.service import IngestionRepository, StorageService
from backend.database.service.staging.schema import FileInfo
from backend.domain.processing.models import FileStatus
from backend.timezone import now_vietnam

SUPPORTED_CONTENT_TYPES = {
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ParentNotFoundError(Exception):
    pass


class ParentArtifactExpiredError(Exception):
    pass


class IngestionService:
    def __init__(
        self,
        staging_repository_service: IngestionRepository,
        storage_service: StorageService,
    ):
        self._repository = staging_repository_service
        self._storage = storage_service

    async def get_upload(
        self, file: RequestPresignedCreate, *, facility_id: UUID
    ) -> RequestPresignedResponse:
        if file.content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError(
                f"Unsupported format {file.content_type} - {file.filename}"
            )

        file_id: UUID = uuid4()
        filename = _get_safe_filename(file.filename)
        now = now_vietnam()
        object_key: str = f"{facility_id}/{now:%Y_%m_%d}/{file_id}/{filename}"

        presigned_url = self._storage.presign_put(
            object_key=object_key,
            content_type=file.content_type,
            base64_hashed_digest=file.base64_hashed_digest,
        )

        return RequestPresignedResponse(
            file_id=file_id,
            object_key=object_key,
            presigned_url=presigned_url,
        )

    async def complete_upload(
        self,
        completion_request: CompleteUploadCreate,
        *,
        facility_id: UUID,
    ) -> CompleteUploadResponse | None:
        complete_object_key = f"{facility_id}/{completion_request.created_at}/{completion_request.object_key}"

        file_metadata = await self._storage.get_file_metadata(complete_object_key)

        if completion_request.size_bytes != int(file_metadata.get("ContentLength", 0)):
            raise ValueError(
                "Uploaded object size does not match the completion request"
            )
        now = now_vietnam()

        file_info = FileInfo(
            id=completion_request.file_id,
            facility_id=facility_id,
            filename=completion_request.filename,
            object_key=complete_object_key,
            content_type=completion_request.content_type,
            size_bytes=completion_request.size_bytes,
            mappings=completion_request.mappings,
            status=FileStatus.QUEUED,
            queued_at=now,
            error_code=None,
            error_message=None,
        )

        complete = await self._repository.create(file_info)

        return _serialize_complete_response(complete) if complete else None


__all__ = [
    "SUPPORTED_CONTENT_TYPES",
    "XLSX_CONTENT_TYPE",
    "IngestionService",
    "ParentArtifactExpiredError",
    "ParentNotFoundError",
]
