import logging

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.schema import CreateSchema
from sqlalchemy.exc import IntegrityError
from uuid import UUID
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.errors import DuplicatedContentError
from backend.database.schema import FileErrorRecord, FileInfo, FileStatus, Base
from backend.domain.ingestion.contracts import QualityIssue

logger = logging.getLogger(__name__)


class IngestionRepository:
    def __init__(self, config: RDBAsyncConnectionConfig):
        self._session = config.async_session_local
        self._engine = config.async_engine

    async def create_table_and_schema(self, orm_object: Base) -> bool:
        async with self._engine.begin() as connection:
            await connection.execute(
                CreateSchema(orm_object.__table__.schema, if_not_exists=True)
            )
            await connection.run_sync(orm_object.__table__.create, checkfirst=True)

        return 1

    async def create(self, file: FileInfo) -> FileInfo | None:
        async with self._session.begin() as session:
            session.add(file)
            return file

    async def get(self, file_id: UUID) -> FileInfo | None:
        async with self._session.begin() as session:
            return await session.get(FileInfo, file_id)

    async def update(self, file_id: UUID, values: dict[str, Any]) -> FileInfo | None:
        async with self._session.begin() as session:
            result = await session.execute(
                update(FileInfo)
                .where(FileInfo.id == file_id)
                .values(**values)
                .returning(FileInfo)
            )

            return result.scalar_one_or_none()

    async def mark_succeeded(self, file_id: UUID, values: dict[str, Any]) -> FileInfo | None:
        """Transition only a claimed file from PROCESSING to SUCCEED."""
        async with self._session.begin() as session:
            result = await session.execute(
                update(FileInfo)
                .where(FileInfo.id == file_id, FileInfo.status == FileStatus.PROCESSING)
                .values(**values, status=FileStatus.SUCCEED)
                .returning(FileInfo)
            )
            return result.scalar_one_or_none()

    async def mark_failed(self, file_id: UUID, values: dict[str, Any]) -> FileInfo | None:
        """Transition only a claimed file from PROCESSING to ERROR."""
        async with self._session.begin() as session:
            result = await session.execute(
                update(FileInfo)
                .where(FileInfo.id == file_id, FileInfo.status == FileStatus.PROCESSING)
                .values(**values, status=FileStatus.ERROR)
                .returning(FileInfo)
            )
            return result.scalar_one_or_none()

    async def requeue_for_retry(self, file_id: UUID) -> FileInfo | None:
        """Allow a Celery retry to reclaim an infrastructure-failed job."""
        async with self._session.begin() as session:
            result = await session.execute(
                update(FileInfo)
                .where(FileInfo.id == file_id, FileInfo.status == FileStatus.ERROR)
                .values(status=FileStatus.QUEUED, error_code=None, error_message=None)
                .returning(FileInfo)
            )
            return result.scalar_one_or_none()

    async def persist_quality_issues(self, issues: list[QualityIssue]) -> int:
        """Persist issues with their source and transformation lineage."""
        if not issues:
            return 0
        values = [
            {
                "file_id": issue.source_file_id,
                "column": issue.source_column,
                "normalized_column": issue.normalized_column,
                "target_field": issue.target_field,
                "row_number": issue.source_row_number,
                "raw_value": self._as_text(issue.raw_value),
                "normalized_value": self._as_text(issue.normalized_value),
                "error": issue.issue_code,
                "issue_code": issue.issue_code,
                "severity": issue.severity.value,
                "message": issue.message,
            }
            for issue in issues
        ]
        async with self._session.begin() as session:
            await session.execute(
                pg_insert(FileErrorRecord)
                .values(values)
                .on_conflict_do_nothing(constraint="ingestion_error_lineage_unique")
            )
        return len(values)

    @staticmethod
    def _as_text(value: Any) -> str | None:
        return None if value is None else str(value)

    async def complete_upload(
        self,
        file_id: UUID,
        content_hash: str,
        size_bytes: int,
        mappings: dict[str, str],
    ) -> FileInfo | None:
        try:
            values = {
                "content_hash": content_hash,
                "size_bytes": size_bytes,
                "status": FileStatus.QUEUED,
                "mappings": mappings,
                "uploaded_at": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")),
                "error_code": None,
                "error_message": None,
            }
            async with self._session.begin() as session:
                result = await session.execute(
                    update(FileInfo)
                    .where(FileInfo.id == file_id)
                    .values(**values)
                    .returning(FileInfo)
                )
                return result.scalar_one_or_none()

        except IntegrityError as exc:
            if "content_hash" in str(exc.orig).lower():
                raise DuplicatedContentError
            raise

    async def claim(self, file_id: UUID) -> tuple[str, dict | None] | None:
        """Atomically transition QUEUED → PROCESSING. Returns (object_key, mappings) or None."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from sqlalchemy import update
        
        async with self._session.begin() as session:
            result = await session.execute(
                update(FileInfo)
                .where(FileInfo.id == file_id, FileInfo.status == FileStatus.QUEUED)
                .values({
                    "status": FileStatus.PROCESSING,
                    "started_at": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")),
                })
                .returning(FileInfo.object_key, FileInfo.mappings)
            )
            row = result.one_or_none()
        return (row.object_key, row.mappings) if row is not None else None
