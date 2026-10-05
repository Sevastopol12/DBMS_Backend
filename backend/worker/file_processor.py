from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from backend.database.errors import FileObjectNotFound, StorageUnavailable
from backend.database.service import (
    IngestionRepository,
    ReportRepository,
    StorageService,
)
from backend.database.service.production.repository import ReviewInput
from backend.domain.processing.engine import TransformPipeline
from backend.domain.processing.mapping import MappingSourceUnavailable
from backend.domain.processing.models import (
    FileAcceptancePolicy,
    FileDecision,
    FileStatus,
    ProcessingStage,
    QualityReport,
)
from backend.domain.processing.reader.errors import ReaderError
from backend.timezone import now_vietnam

from . import error_codes

logger = logging.getLogger(__name__)


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
            logger.info("file_id=%s claim=none", file_id)
            return

        try:
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
                    await self._reject_input(file_id, error_codes.EMPTY_INPUT)
                    return
            except FileObjectNotFound:
                await self._fail(file_id, error_codes.SOURCE_OBJECT_NOT_FOUND)
                return
            except StorageUnavailable:
                await self._fail(file_id, error_codes.STORAGE_UNAVAILABLE)
                return

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
                await self._fail(file_id, error_codes.MAPPING_SOURCE_UNAVAILABLE)
                return
            except ReaderError as exc:
                await self._reject_input(
                    file_id,
                    self._reader_error_code(exc),
                    mapping_source=mapping_source_value,
                )
                return
            except Exception:  # noqa: BLE001 - unexpected exception maps to UNEXPECTED_TRANSFORM_ERROR
                await self._fail(file_id, error_codes.UNEXPECTED_TRANSFORM_ERROR)
                return

            if result.quality_report.decision is FileDecision.REJECTED:
                await self._reject_result(
                    file_id, result.quality_report, mapping_source_value, file_info
                )
                return

            if file_info is None or file_info.facility_id is None:
                await self._fail(file_id, error_codes.PERSISTENCE_FAILED)
                return

            reviews = [
                ReviewInput(
                    source_row_number=review.source_row_number,
                    disposition=review.disposition.value,
                    issue_codes=review.issue_codes,
                )
                for review in result.review_records
            ]
            try:
                persistence = await self._production.replace_file_result(
                    source_file_id=file_id,
                    facility_id=file_info.facility_id,
                    rows=result.accepted_rows,
                    source_row_numbers=result.accepted_row_numbers,
                    reviews=reviews,
                    source_size_bytes=file_info.size_bytes,
                )
            except Exception:
                await self._fail(file_id, error_codes.PERSISTENCE_FAILED)
                raise

            result.quality_report.metadata.update(
                {
                    "persistence_attempted": persistence.attempted,
                    "persistence_inserted": persistence.inserted,
                    "persistence_skipped": 0,
                    "review_rows": persistence.reviews_inserted,
                    "replaced_report_rows": persistence.deleted_reports,
                    "mapping_source": mapping_source_value,
                }
            )
            result.quality_report.facility_id = file_info.facility_id
            await self._staging.update(
                file_id,
                {
                    "status": FileStatus.SUCCEED,
                    "completed_at": now_vietnam(),
                    "accepted_row_count": result.accepted_row_count,
                    "rejected_row_count": result.rejected_row_count,
                    "quality_report": result.quality_report.model_dump(mode="json"),
                    "error_code": None,
                    "error_message": None,
                },
            )
            self._log_terminal(
                file_id,
                FileStatus.SUCCEED,
                attempt=(getattr(file_info, "attempt_count", None) if file_info is not None else None),
                rows_accepted=result.accepted_row_count,
                rows_review=persistence.reviews_inserted,
            )
        except Exception as exc:
            logger.exception(
                "file_id=%s unexpected_exception=%s", file_id, type(exc).__name__
            )
            try:
                await self._fail(file_id, error_codes.UNEXPECTED_ERROR)
            except Exception as fail_exc:  # noqa: BLE001 - must not mask original failure
                logger.error(
                    "file_id=%s fail_exception=%s", file_id, type(fail_exc).__name__
                )
            raise

    async def _reject_result(
        self,
        file_id: UUID,
        report: QualityReport,
        mapping_source: str,
        file_info: Any,
        error_code: str | None = None,
    ) -> None:
        try:
            deleted_reports, _deleted_reviews = await self._production.purge_file(file_id)
        except Exception:  # noqa: BLE001 - purge failure maps to PERSISTENCE_FAILED
            await self._fail(file_id, error_codes.PERSISTENCE_FAILED)
            return
        report.metadata.update(
            {
                "persistence_attempted": 0,
                "persistence_inserted": 0,
                "persistence_skipped": 0,
                "review_rows": 0,
                "replaced_report_rows": deleted_reports,
                "mapping_source": mapping_source,
            }
        )
        report.facility_id = file_info.facility_id if file_info is not None else None
        await self._staging.update(
            file_id,
            {
                "status": FileStatus.REJECTED,
                "completed_at": now_vietnam(),
                "accepted_row_count": 0,
                "rejected_row_count": report.total_rows,
                "quality_report": report.model_dump(mode="json"),
                "error_code": error_code,
                "error_message": error_code,
            },
        )
        self._log_terminal(file_id, FileStatus.REJECTED)

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
                "completed_at": now_vietnam(),
                "last_error_at": now_vietnam(),
                "error_code": error_code,
                "error_message": error_code,
            },
        )
        self._log_terminal(file_id, FileStatus.ERROR, code=error_code)

    async def _reject_input(
        self, file_id: UUID, error_code: str, *, mapping_source: str = "NONE"
    ) -> None:
        report = QualityReport(
            file_id=file_id,
            decision=FileDecision.REJECTED,
            processing_stage=ProcessingStage.STRUCTURAL,
            metadata={"input_rejection": error_code},
        )
        file_info = await self._staging.get(file_id)
        await self._reject_result(
            file_id, report, mapping_source, file_info, error_code=error_code
        )

    @staticmethod
    def _log_terminal(
        file_id: UUID,
        status: FileStatus,
        *,
        code: str | None = None,
        attempt: int | None = None,
        rows_accepted: int = 0,
        rows_review: int = 0,
    ) -> None:
        logger.info(
            "file_id=%s status=%s code=%s attempt=%s rows_accepted=%s rows_review=%s",
            file_id,
            status.value,
            code,
            attempt,
            rows_accepted,
            rows_review,
        )

    @staticmethod
    def _reader_error_code(error: ReaderError) -> str:
        return {
            "UnsupportedFormatError": error_codes.UNSUPPORTED_FORMAT,
            "UnsupportedDelimiterError": error_codes.UNSUPPORTED_DELIMITER,
            "UnreadableInputError": error_codes.UNREADABLE_INPUT,
            "CorruptFileError": error_codes.CORRUPT_INPUT,
            "EmptyFileError": error_codes.EMPTY_INPUT,
            "EmptyWorksheetError": error_codes.EMPTY_INPUT,
        }.get(type(error).__name__, error_codes.INVALID_INPUT)


__all__ = ["FileProcessor"]
