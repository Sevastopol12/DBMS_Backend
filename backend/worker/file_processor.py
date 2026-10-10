from __future__ import annotations

import logging
import os
from typing import Any
from uuid import UUID

from backend.database.errors import FileObjectNotFound, StorageUnavailable
from backend.database.service import IngestionRepository, StorageService
from backend.database.service.production.persistence import (
    AcceptedDataPersistence,
    PersistRecord,
    PersistRequest,
    PersistReview,
)
from backend.database.service.storage import (
    artifact_expires_at,
    rejection_key_for_file,
)
from backend.domain.processing.artifact.rejection_xlsx import build_rejection_xlsx
from backend.domain.processing.engine import TransformPipeline
from backend.domain.processing.mapping import MappingSourceUnavailable
from backend.domain.processing.models import (
    FileAcceptancePolicy,
    FileDecision,
    FileStatus,
    ProcessingStage,
    QualityReport,
    RowDisposition,
    TransformResult,
)
from backend.domain.processing.reader.errors import ReaderError
from backend.timezone import now_vietnam

from . import error_codes

logger = logging.getLogger(__name__)

_XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_MAPPING_COVERAGE_REASON = "MAPPING_COVERAGE_BELOW_MINIMUM"


def max_source_rows_from_env() -> int:
    """Data-row limit for one file (A-3); ``0`` means unlimited."""

    try:
        return int(os.getenv("MAX_SOURCE_ROWS", "50000"))
    except ValueError:
        return 50000


class FileProcessor:
    """Application adapter connecting storage, pipeline and repositories."""

    def __init__(
        self,
        staging_repository: IngestionRepository,
        persistence: AcceptedDataPersistence,
        storage: StorageService,
        mapping_provider: Any | None = None,
        policy: FileAcceptancePolicy | None = None,
        operation_handlers: dict[Any, Any] | None = None,
    ) -> None:
        self._staging = staging_repository
        self._persistence = persistence
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
                transformed_at = now_vietnam()
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

            if self._over_row_limit(result):
                self._mark_row_limit_rejection(result)
                await self._reject_file_level(
                    file_id,
                    result,
                    mapping_source_value,
                    file_info,
                    error_code=error_codes.ROW_LIMIT_EXCEEDED,
                    file_level_reason=error_codes.ROW_LIMIT_EXCEEDED,
                )
                return

            if result.quality_report.decision is FileDecision.REJECTED:
                await self._reject_file_level(
                    file_id,
                    result,
                    mapping_source_value,
                    file_info,
                    error_code=None,
                    file_level_reason=_MAPPING_COVERAGE_REASON,
                )
                return

            if (
                file_info is None
                or file_info.facility_id is None
                or file_info.uploaded_at is None
            ):
                await self._fail(file_id, error_codes.PERSISTENCE_FAILED)
                return

            request = self._persist_request(
                result,
                facility_id=file_info.facility_id,
                source_file_uploaded_at=file_info.uploaded_at,
                transformed_at=transformed_at,
            )

            (
                artifact_key,
                artifact_created,
                artifact_expires,
            ) = await self._write_success_artifact(
                file_id, result, facility_id=file_info.facility_id
            )
            if artifact_key is None and self._needs_success_artifact(result):
                # _write_success_artifact already recorded ARTIFACT_WRITE_FAILED.
                return

            try:
                persistence = await self._persistence.persist(request)
            except Exception as persist_exc:  # noqa: BLE001 - any persist failure maps to PERSISTENCE_FAILED
                logger.error(
                    "file_id=%s persist_exception=%s",
                    file_id,
                    type(persist_exc).__name__,
                )
                await self._fail(file_id, error_codes.PERSISTENCE_FAILED)
                return

            result.quality_report.metadata.update(
                {
                    "persistence_attempted": persistence.attempted,
                    "persistence_applied": persistence.applied,
                    "persistence_superseded": persistence.superseded,
                    "persistence_released": persistence.released,
                    "reviews_written": persistence.reviews_written,
                    "mapping_source": mapping_source_value,
                }
            )
            result.quality_report.facility_id = file_info.facility_id
            values: dict[str, Any] = {
                "status": FileStatus.SUCCEED,
                "completed_at": now_vietnam(),
                "accepted_row_count": result.accepted_row_count,
                "rejected_row_count": result.rejected_row_count,
                "ignored_duplicate_row_count": result.ignored_duplicate_row_count,
                "quality_report": result.quality_report.model_dump(mode="json"),
                "error_code": None,
                "error_message": None,
            }
            if artifact_key is not None and artifact_expires is not None:
                values["rejection_artifact_key"] = artifact_key
                values["rejection_artifact_expires_at"] = artifact_expires
                values["artifact_created_at"] = artifact_created
                values["artifact_purged_at"] = None
            await self._staging.update(file_id, values)
            self._log_terminal(
                file_id,
                FileStatus.SUCCEED,
                attempt=(
                    getattr(file_info, "attempt_count", None)
                    if file_info is not None
                    else None
                ),
                rows_accepted=result.accepted_row_count,
                rows_review=persistence.reviews_written,
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

    def _persist_request(
        self,
        result: TransformResult,
        *,
        facility_id: UUID,
        source_file_uploaded_at: Any,
        transformed_at: Any,
    ) -> PersistRequest:
        records = [
            PersistRecord(values=dict(record.row.model_dump()))
            for record in result.accepted_records
        ]
        reviews = [
            PersistReview(
                source_row_number=decision.source_row_number,
                disposition=decision.disposition.value,
                duplicate_role=decision.duplicate_role.value,
                merged_into_row=decision.merged_into_row,
                group_row_numbers=list(decision.group_row_numbers),
                issue_codes=list(decision.issue_codes),
            )
            for decision in result.decisions
        ]
        return PersistRequest(
            source_file_id=result.file_id,
            facility_id=facility_id,
            source_filename=result.filename,
            source_file_uploaded_at=source_file_uploaded_at,
            transformed_at=transformed_at,
            records=records,
            reviews=reviews,
        )

    def _over_row_limit(self, result: TransformResult) -> bool:
        limit = max_source_rows_from_env()
        if limit == 0:
            return False
        return result.quality_report.total_rows > limit

    @staticmethod
    def _mark_row_limit_rejection(result: TransformResult) -> None:
        total = result.quality_report.total_rows
        result.quality_report.decision = FileDecision.REJECTED
        result.quality_report.processing_stage = ProcessingStage.POLICY
        result.quality_report.accepted_rows = 0
        result.quality_report.rejected_rows = total
        result.quality_report.ignored_duplicate_row_count = 0
        result.accepted_records = []
        result.accepted_row_count = 0
        result.rejected_row_count = total
        result.ignored_duplicate_row_count = 0
        result.quality_report.issue_code_counts[error_codes.ROW_LIMIT_EXCEEDED] = (
            result.quality_report.issue_code_counts.get(
                error_codes.ROW_LIMIT_EXCEEDED, 0
            )
            + 1
        )

    @staticmethod
    def _needs_success_artifact(result: TransformResult) -> bool:
        return any(
            decision.disposition is RowDisposition.REJECTED
            for decision in result.decisions
        )

    async def _write_success_artifact(
        self, file_id: UUID, result: TransformResult, *, facility_id: UUID
    ) -> tuple[str | None, Any, Any]:
        if result.source is None or not self._needs_success_artifact(result):
            return None, None, None
        try:
            payload = build_rejection_xlsx(
                result.source,
                result.decisions,
                file_level_reason=None,
                file_id=file_id,
            )
            key = rejection_key_for_file(facility_id, file_id)
            await self._storage.put_object(key, payload, _XLSX_CONTENT_TYPE)
            created = now_vietnam()
            return key, created, artifact_expires_at(created)
        except Exception:  # noqa: BLE001 - any artifact failure maps to ARTIFACT_WRITE_FAILED
            await self._fail(file_id, error_codes.ARTIFACT_WRITE_FAILED)
            return None, None, None

    async def _reject_file_level(
        self,
        file_id: UUID,
        result: TransformResult,
        mapping_source: str,
        file_info: Any,
        *,
        error_code: str | None,
        file_level_reason: str | None,
    ) -> None:
        report = result.quality_report
        try:
            released = await self._persistence.release_file(file_id)
        except Exception:  # noqa: BLE001 - release failure maps to PERSISTENCE_FAILED
            await self._fail(file_id, error_codes.PERSISTENCE_FAILED)
            return

        artifact_key: str | None = None
        artifact_created: Any = None
        artifact_expires: Any = None
        if (
            file_level_reason is not None
            and result.source is not None
            and report.total_rows > 0
            and file_info is not None
            and getattr(file_info, "facility_id", None) is not None
        ):
            try:
                payload = build_rejection_xlsx(
                    result.source,
                    result.decisions,
                    file_level_reason=file_level_reason,
                    file_id=file_id,
                )
                artifact_key = rejection_key_for_file(file_info.facility_id, file_id)
                await self._storage.put_object(
                    artifact_key, payload, _XLSX_CONTENT_TYPE
                )
                artifact_created = now_vietnam()
                artifact_expires = artifact_expires_at(artifact_created)
            except Exception:  # noqa: BLE001 - any artifact failure maps to ARTIFACT_WRITE_FAILED
                await self._fail(file_id, error_codes.ARTIFACT_WRITE_FAILED)
                return

        report.metadata.update(
            {
                "persistence_attempted": 0,
                "persistence_applied": 0,
                "persistence_superseded": 0,
                "persistence_released": released,
                "reviews_written": 0,
                "mapping_source": mapping_source,
            }
        )
        report.facility_id = file_info.facility_id if file_info is not None else None
        values: dict[str, Any] = {
            "status": FileStatus.REJECTED,
            "completed_at": now_vietnam(),
            "accepted_row_count": 0,
            "rejected_row_count": report.total_rows,
            "ignored_duplicate_row_count": 0,
            "quality_report": report.model_dump(mode="json"),
            "error_code": error_code,
            "error_message": error_code,
        }
        if artifact_key is not None and artifact_expires is not None:
            values["rejection_artifact_key"] = artifact_key
            values["rejection_artifact_expires_at"] = artifact_expires
            values["artifact_created_at"] = artifact_created
            values["artifact_purged_at"] = None
        await self._staging.update(file_id, values)
        self._log_terminal(file_id, FileStatus.REJECTED)

    async def _reject_result(
        self,
        file_id: UUID,
        report: QualityReport,
        mapping_source: str,
        file_info: Any,
        error_code: str | None = None,
    ) -> None:
        try:
            released = await self._persistence.release_file(file_id)
        except Exception:  # noqa: BLE001 - release failure maps to PERSISTENCE_FAILED
            await self._fail(file_id, error_codes.PERSISTENCE_FAILED)
            return
        report.metadata.update(
            {
                "persistence_attempted": 0,
                "persistence_applied": 0,
                "persistence_superseded": 0,
                "persistence_released": released,
                "reviews_written": 0,
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
                "ignored_duplicate_row_count": 0,
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


__all__ = ["FileProcessor", "max_source_rows_from_env"]
