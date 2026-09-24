from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.errors import (
    DuplicatedContentError,
    is_duplicate_content_integrity_error,
)
from backend.database.schema import Base, FileInfo, FileStatus


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

    async def complete_upload(
        self,
        file_id: UUID,
        content_hash: str,
        size_bytes: int,
        mappings: dict[str, object] | None,
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
            if is_duplicate_content_integrity_error(exc):
                raise DuplicatedContentError
            raise

    async def claim(
        self,
        file_id: UUID,
        *,
        processing_timeout: timedelta = timedelta(minutes=15),
    ) -> tuple[str, dict | None] | None:
        """Atomically claim queued work or reclaim stale PROCESSING work."""
        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        stale_before = now - processing_timeout
        async with self._session.begin() as session:
            result = await session.execute(
                update(FileInfo)
                .where(
                    FileInfo.id == file_id,
                    or_(
                        FileInfo.status == FileStatus.QUEUED,
                        (
                            (FileInfo.status == FileStatus.PROCESSING)
                            & (
                                FileInfo.started_at.is_(None)
                                | (FileInfo.started_at <= stale_before)
                            )
                        ),
                    ),
                )
                .values(
                    {
                        "status": FileStatus.PROCESSING,
                        "started_at": now,
                    }
                )
                .returning(FileInfo.object_key, FileInfo.mappings)
            )
            row = result.one_or_none()
        return (row.object_key, row.mappings) if row is not None else None

    async def recover_processing(
        self, *, processing_timeout: timedelta = timedelta(minutes=15)
    ) -> list[UUID]:
        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        stale_before = now - processing_timeout
        async with self._session.begin() as session:
            result = await session.execute(
                update(FileInfo)
                .where(
                    FileInfo.status == FileStatus.PROCESSING,
                    or_(
                        FileInfo.started_at.is_(None),
                        FileInfo.started_at <= stale_before,
                    ),
                )
                .values({"status": FileStatus.QUEUED, "started_at": None})
                .returning(FileInfo.id)
            )
            return list(result.scalars().all())
