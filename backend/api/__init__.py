from fastapi import APIRouter
import logging

from typing import Annotated
from fastapi import Depends, BackgroundTasks
from fastapi.exceptions import HTTPException

from backend.database import get_staging_rdb, get_staging_storage
from backend.database.service import RDBService, StorageService
from backend.database.errors import FileDuplicatedError

from backend.domain import get_presigned_url, record_file_upload
from backend.domain.models import FileRecord, FileRegister, ResponseURL, RecordedResult


logger = logging.getLogger(__name__)

router = APIRouter()


RelationalDatabaseService = Annotated[RDBService, Depends(get_staging_rdb)]
FileStorageService = Annotated[StorageService, Depends(get_staging_storage)]


@router.post("/upload")
def request_presigned_url(
    registry: FileRegister, storage_service: FileStorageService
) -> ResponseURL:
    presigned_url: ResponseURL = get_presigned_url(registry, storage_service)
    return presigned_url


@router.post("/record")
async def load_record(
    record: FileRecord,
    rdb_service: RelationalDatabaseService,
    background: BackgroundTasks,
) -> RecordedResult:
    try:
        result: RecordedResult = await record_file_upload(record, rdb_service)
        return result

    except FileDuplicatedError as e:
        raise HTTPException(status_code=203, detail=str(e))
