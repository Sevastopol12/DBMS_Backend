from uuid import UUID, uuid4

from backend.api.dto import (
    IngestionComplete,
    IngestionCreate,
    IngestionResponse,
    _get_safe_filename,
    _serialize_ingestion,
)
from backend.database.service import IngestionRepository, StorageService
from backend.database.service.staging.schema import FileInfo
from backend.domain.processing.models import FileStatus
from backend.timezone import now_vietnam

SUPPORTED_CONTENT_TYPES = {
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class IngestionService:
    def __init__(
        self,
        staging_repository_service: IngestionRepository,
        storage_service: StorageService,
    ):
        self._repository = staging_repository_service
        self._storage = storage_service

    async def get_upload(self, file: IngestionCreate) -> IngestionResponse:
        if file.content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError(
                f"Unsupported format {file.content_type} - {file.filename}"
            )

        file_id: UUID = uuid4()
        facility_id: UUID = file.facility_id
        filename = _get_safe_filename(file.filename)
        created_at = now_vietnam()
        object_key: str = f"{created_at:%Y_%m_%d}/{file_id}/{filename}"

        file_info = FileInfo(
            id=file_id,
            facility_id=facility_id,
            filename=filename,
            object_key=object_key,
            content_type=file.content_type,
            status=FileStatus.CREATED,
            created_at=created_at,
        )

        await self._repository.create(file_info)
        presigned_url = self._storage.get_presigned_url(
            object_key=object_key, content_type=file.content_type
        )

        return _serialize_ingestion(file_info, presigned_url)

    async def complete_upload(
        self,
        data: IngestionComplete,
    ) -> IngestionResponse | None:
        try:
            file = await self._repository.get(data.id)

            if file is None:
                return None

            if file.status in {FileStatus.QUEUED, FileStatus.PROCESSING}:
                return _serialize_ingestion(file)

            file_metadata = await self._storage.get_file_metadata(file.object_key)

            if data.size_bytes != int(file_metadata.get("ContentLength", 0)):
                raise ValueError(
                    "Uploaded object size does not match the completion request"
                )

            complete = await self._repository.complete_upload(
                data.id, data.content_hash, data.size_bytes, data.mappings
            )

            return _serialize_ingestion(complete) if complete else None

        except Exception:
            await self._repository.update(
                data.id,
                {
                    "status": FileStatus.ERROR,
                    "error_code": "INTERNAL_ERROR",
                    "error_message": "Upload completion failed",
                    "last_error_at": now_vietnam(),
                },
            )
            raise


__all__ = ["SUPPORTED_CONTENT_TYPES", "IngestionService"]
