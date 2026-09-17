from __future__ import annotations
import logging
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from backend.database.service import IngestionRepository, StorageService
from backend.database.service.repository.production import ReportRepository
from backend.domain.ingestion.contracts import TransformResult
from backend.domain.ingestion.pipeline import TransformationPipeline


logger = logging.getLogger(__name__)
_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class InfrastructureProcessingError(RuntimeError):
    """A retryable storage, parser, or database failure during ingestion."""


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

    async def process_file(self, file_id: UUID) -> bool:
        claimed = await self._staging.claim(file_id)
        if claimed is None:
            logger.warning(
                "File %s could not be claimed (not QUEUED or not found)", file_id
            )
            return False

        object_key, mappings = claimed
        try:
            file_bytes = self._storage.get(object_key)
            if file_bytes is None:
                raise ValueError("File has no content")

        except ValueError as exc:
            await self._fail(file_id, "NULL_CONTENT", str(exc))
            return True

        except Exception as exc:
            await self._fail(file_id, "STORAGE_UNAVAILABLE", str(exc))
            raise InfrastructureProcessingError("Storage download failed") from exc

        try:
            file_info = await self._staging.get(file_id)
            if file_info is None:
                raise ValueError("File metadata is unavailable")
        except Exception as exc:
            await self._fail(file_id, "METADATA_UNAVAILABLE", str(exc))
            raise InfrastructureProcessingError("File metadata unavailable") from exc

        try:
            result = await self._apply_transform(
                file_id, file_bytes, file_info.filename, mappings
            )
        except Exception as exc:
            logger.exception("Unexpected transformation error for file %s", file_id)
            await self._fail(file_id, "TRANSFORMATION_FAILED", str(exc))
            raise InfrastructureProcessingError("Transformation failed") from exc

        # Persist accepted rows
        try:
            size_bytes = file_info.size_bytes if file_info else None
            await self._production.bulk_insert(
                result.accepted_rows,
                source_file_id=file_id,
                source_size_bytes=size_bytes,
            )
            await self._staging.persist_quality_issues(result.quality_issues)
        except Exception as exc:
            await self._fail(file_id, "PERSISTENCE_FAILED", str(exc))
            raise InfrastructureProcessingError("Persistence failed") from exc

        completed = await self._staging.mark_succeeded(
            file_id,
            {
                "completed_at": datetime.now(_TZ),
                "accepted_row_count": result.accepted_row_count,
                "rejected_row_count": result.rejected_row_count,
            },
        )
        if completed is None:
            raise InfrastructureProcessingError("Lost PROCESSING ownership before completion")
        return True

    async def _apply_transform(
        self,
        file_id: UUID,
        file_bytes: bytes,
        filename: str,
        mappings: dict | None,
    ) -> TransformResult:
        return TransformationPipeline().process(
            file_bytes=file_bytes,
            filename=filename,
            source_file_id=file_id,
            mappings=mappings,
        )

    async def _fail(self, file_id: UUID, code: str, message: str) -> None:
        await self._staging.mark_failed(
            file_id,
            {
                "error_code": code,
                "error_message": message[:2000],
                "completed_at": datetime.now(_TZ),
            },
        )
