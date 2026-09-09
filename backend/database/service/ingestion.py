from .rdb import IngestionRepository
from .storage import StorageService
from ..utils import _get_safe_filename, _serialize_ingestion
from ..errors import DuplicatedContentError

from backend.domain.models import IngestionCreate, IngestionResponse, IngestionComplete
from backend.database.schema import FileInfo, FileStatus

from uuid import UUID, uuid4
from datetime import datetime

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
        object_key: str = f"ingestion/{datetime.now():%Y_%m_%d}/{file_id}/{filename}"

        file = FileInfo(
            id=file_id,
            filename=filename,
            object_key=object_key,
            content_type=file.content_type,
            status=FileStatus.CREATED,
            created_at=datetime.now(),
        )

        await self._repository.create(file)
        presigned_url = await self._storage.get_presigned_url(
            object_key=object_key, content_type=file.content_type
        )

        return _serialize_ingestion(file, presigned_url)

    async def complete_upload(
        self,
        data: IngestionComplete,
    ) -> IngestionResponse | None:
        file = await self._repository.get(data.file_id)

        if file is None:
            return None

        if file.status in {
            FileStatus.QUEUED,
            FileStatus.PROCESSING,
        }:
            return _serialize_ingestion(file)

        file_metadata = self._storage.get_file_metadata(file.obj_key)

        if data.size_bytes == int(file_metadata.get("ContentLength", 0)):
            raise ValueError(
                "Uploaded object size does not match the completion request"
            )

        complete = await self._repository.complete_upload(
            data.file_id, data.content_hash, data.size_bytes, data.mappings
        )

        return _serialize_ingestion(complete) if complete else None
