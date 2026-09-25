from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from backend.api.dto import (
    IngestionComplete,
    IngestionCreate,
    IngestionResponse,
    _get_safe_filename,
    _serialize_ingestion,
)
from backend.database.service import StorageService, IngestionRepository
from backend.database.service.staging.schema import FileInfo
from backend.domain.processing.models import FileStatus


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
        filename = _get_safe_filename(file.filename)
        object_key: str = (
            f"{datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')):%Y_%m_%d}/"
            f"{file_id}/{filename}"
        )

        file_info = FileInfo(
            id=file_id,
            filename=filename,
            object_key=object_key,
            content_type=file.content_type,
            status=FileStatus.CREATED,
            facility_id=uuid4(),
            created_at=datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")),
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

        except Exception as exc:
            await self._repository.update(
                data.id,
                {
                    "status": FileStatus.ERROR,
                    "error_code": "INTERNAL_ERROR",
                    "error_message": str(exc),
                },
            )
            raise


__all__ = ["IngestionService", "SUPPORTED_CONTENT_TYPES"]
