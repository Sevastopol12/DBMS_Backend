from backend.database.service import RDBService, StorageService
from .models import FileRecord, FileRegister, RecordedResult, ResponseURL


def get_presigned_url(
    registry: FileRegister,
    storage_service: StorageService,
) -> ResponseURL:
    result = storage_service.get_presigned_url(
        filename=registry.filename, content_type=registry.content_type
    )
    return ResponseURL(presigned_url=result)


async def record_file_upload(
    record: FileRecord, rdb_service: RDBService
) -> RecordedResult:
    result = await rdb_service.record(
        filename=record.filename, file_hash=record.hashed_value
    )

    return RecordedResult(**result)
