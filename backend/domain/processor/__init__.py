from __future__ import annotations
import logging
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from backend.database.service import IngestionRepository, StorageService
from backend.database.service.repository.production import ReportRepository
from backend.domain.models import FileStatus


logger = logging.getLogger(__name__)
_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class FileProcessor:
    def __init__(
        self,
        staging_repository: IngestionRepository,
        production_repository: ReportRepository,
        storage: StorageService,
    ) -> None:
        self._staging = staging_repository
        self._production = production_repository
        self._storage = storage

    async def process_file(self, file_id: UUID) -> None:
        claimed = await self._staging.claim(file_id)
        if claimed is None:
            logger.warning(
                "File %s could not be claimed (not QUEUED or not found)", file_id
            )
            return

        object_key, mappings = claimed
        try:
            file_bytes = self._storage.get(object_key).read()
        except Exception as exc:
            await self._fail(file_id, "STORAGE_UNAVAILABLE", str(exc))
            return

        try:
            result = await self._apply_transform(file_id, file_bytes, mappings)
        except Exception as exc:
            logger.exception("Unexpected transformation error for file %s", file_id)
            await self._fail(file_id, "UNEXPECTED_TRANSFORM_ERROR", str(exc))
            return

        # Persist accepted rows
        try:
            file_info = await self._staging.get(file_id)
            size_bytes = file_info.size_bytes if file_info else None
            await self._production.bulk_insert(
                result.rows, source_file_id=file_id, source_size_bytes=size_bytes
            )
        except Exception as exc:
            await self._fail(file_id, "PERSISTENCE_FAILED", str(exc))
            return

        await self._staging.update(
            file_id,
            {
                "status": FileStatus.SUCCEED,
                "completed_at": datetime.now(_TZ),
                "accepted_row_count": result.accepted_row_count,
                "rejected_row_count": result.rejected_row_count,
            },
        )

    async def _apply_transform(
        self, file_id: UUID, file_bytes: bytes, mappings: dict | None
    ):
        #TODO
        ...

    async def _fail(self, file_id: UUID, code: str, message: str) -> None:
        # Use this when an error occured while _apply_transform
        await self._staging.update(
            file_id,
            {
                "status": FileStatus.ERROR,
                "error_code": code,
                "error_message": message[:2000],
                "completed_at": datetime.now(_TZ),
            },
        )
