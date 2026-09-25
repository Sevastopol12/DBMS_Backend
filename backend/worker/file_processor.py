from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from backend.database.errors import FileObjectNotFound, StorageUnavailable
from backend.database.service import (
    ReportRepository,
    IngestionRepository,
    StorageService,
)
from backend.domain.processing.models import (
    FileAcceptancePolicy,
    FileDecision,
    ProcessingStage,
    QualityReport,
)
from backend.domain.processing.engine import TransformPipeline
from backend.domain.processing.mapping import MappingSourceUnavailable
from backend.domain.processing.reader.errors import ReaderError
from backend.domain.processing.models import FileStatus


_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class FileProcessor:
    """Application adapter connecting storage, pipeline and repositories."""

    def __init__(
        self,
        staging_repository: IngestionRepository,
        production_repository: ReportRepository,
        storage: StorageService,
        mapping_provider: Any | None = None,
        policy: FileAcceptancePolicy | None = None,
        operation_handlers: dict[Any, Any] | None = None,
    ) -> None:
        self._staging = staging_repository
        self._production = production_repository
        self._storage = storage
        self._mapping_provider = mapping_provider
        self._policy = policy
        self._operation_handlers = operation_handlers

    async def process_file(self, file_id: UUID) -> None:
        claimed = await self._staging.claim(file_id)
        if claimed is None:
            return

        object_key, mappings = claimed

        file_info = await self._staging.get(file_id)
        filename = (
            file_info.filename
            if file_info is not None
            else object_key.rsplit("/", 1)[-1]
        )

        try:
            file_bytes = self._storage.get(object_key)
            if file_bytes is None:
                await self._reject_input(file_id, "EMPTY_INPUT")
                return
        except FileObjectNotFound:
            await self._fail(file_id, "SOURCE_OBJECT_NOT_FOUND")
            return
        except StorageUnavailable:
            await self._fail(file_id, "STORAGE_UNAVAILABLE")
            return
        except Exception:
            await self._fail(file_id, "STORAGE_UNAVAILABLE")
            return

        # Acquire mapping source before transform.
        source = None
        mapping_source_value = "NONE"
        try:
            if self._mapping_provider is not None:
                source = await self._mapping_provider.acquire()
                mapping_source_value = source.kind.value

            result = await self._apply_transform(
                file_id, filename, file_bytes, mappings, source
            )
        except MappingSourceUnavailable:
            await self._fail(file_id, "MAPPING_SOURCE_UNAVAILABLE")
            return
        except ReaderError as exc:
            error_code = self._reader_error_code(exc)
            await self._reject_input(
                file_id,
                error_code,
                mapping_source=mapping_source_value,
            )
            return
        except Exception:
            await self._fail(file_id, "UNEXPECTED_TRANSFORM_ERROR")
            return

        if result.quality_report.decision is FileDecision.REJECTED:
            result.quality_report.metadata.update(
                {
                    "persistence_attempted": 0,
                    "persistence_inserted": 0,
                    "persistence_skipped": 0,
                    "mapping_source": mapping_source_value,
                }
            )
            report_json = result.quality_report.model_dump(mode="json")
            await self._staging.update(
                file_id,
                {
                    "status": FileStatus.REJECTED,
                    "completed_at": datetime.now(_TZ),
                    "accepted_row_count": 0,
                    "rejected_row_count": result.quality_report.total_rows,
                    "quality_report": report_json,
                },
            )
            return

        if file_info is None or file_info.facility_id is None:
            await self._fail(file_id, "PERSISTENCE_FAILED")
            return

        try:
            persistence = await self._production.bulk_insert(
                result.accepted_rows,
                source_file_id=file_id,
                facility_id=file_info.facility_id,
                source_size_bytes=file_info.size_bytes if file_info else None,
                source_row_numbers=result.accepted_row_numbers,
            )
        except Exception:
            await self._fail(file_id, "PERSISTENCE_FAILED")
            return

        result.quality_report.metadata.update(
            {
                "persistence_attempted": persistence.attempted,
                "persistence_inserted": persistence.inserted,
                "persistence_skipped": persistence.skipped,
                "mapping_source": mapping_source_value,
            }
        )
        report_json = result.quality_report.model_dump(mode="json")

        await self._staging.update(
            file_id,
            {
                "status": FileStatus.SUCCEED,
                "completed_at": datetime.now(_TZ),
                "accepted_row_count": result.accepted_row_count,
                "rejected_row_count": result.rejected_row_count,
                "quality_report": report_json,
                "error_code": None,
                "error_message": None,
            },
        )

    async def _apply_transform(
        self,
        file_id: UUID,
        filename: str,
        file_bytes: bytes | dict,
        mappings: dict | None = None,
        mapping_cache: Any | None = None,
    ):
        pipeline = TransformPipeline(
            mapping_cache=mapping_cache,
            explicit_mapping=mappings,
            policy=self._policy,
            operation_handlers=self._operation_handlers,
        )

        return await pipeline.transform(file_id, filename, file_bytes)

    async def _fail(self, file_id: UUID, error_code: str) -> None:
        await self._staging.update(
            file_id,
            {
                "status": FileStatus.ERROR,
                "completed_at": datetime.now(_TZ),
                "error_code": error_code,
                "error_message": error_code,
            },
        )

    async def _reject_input(
        self, file_id: UUID, error_code: str, *, mapping_source: str = "NONE"
    ) -> None:
        report = QualityReport(
            file_id=file_id,
            decision=FileDecision.REJECTED,
            processing_stage=ProcessingStage.STRUCTURAL,
            metadata={
                "input_rejection": error_code,
                "persistence_attempted": 0,
                "persistence_inserted": 0,
                "persistence_skipped": 0,
                "mapping_source": mapping_source,
            },
        )
        await self._staging.update(
            file_id,
            {
                "status": FileStatus.REJECTED,
                "completed_at": datetime.now(_TZ),
                "accepted_row_count": 0,
                "rejected_row_count": 0,
                "quality_report": report.model_dump(mode="json"),
                "error_code": error_code,
                "error_message": error_code,
            },
        )

    @staticmethod
    def _reader_error_code(error: ReaderError) -> str:
        name = type(error).__name__
        return {
            "UnsupportedFormatError": "UNSUPPORTED_FORMAT",
            "UnsupportedDelimiterError": "UNSUPPORTED_DELIMITER",
            "UnreadableInputError": "UNREADABLE_INPUT",
            "CorruptFileError": "CORRUPT_INPUT",
            "EmptyFileError": "EMPTY_INPUT",
            "EmptyWorksheetError": "EMPTY_INPUT",
        }.get(name, "INVALID_INPUT")


__all__ = ["FileProcessor"]
