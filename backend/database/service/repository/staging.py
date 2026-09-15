import logging

from sqlalchemy import update
from sqlalchemy.schema import CreateSchema
from sqlalchemy.exc import IntegrityError
from uuid import UUID
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.errors import DuplicatedContentError
from backend.database.schema import FileInfo, FileStatus, Base

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
