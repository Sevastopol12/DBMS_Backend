import logging

from sqlalchemy import select, update
from sqlalchemy.schema import CreateSchema
from sqlalchemy.exc import IntegrityError
from uuid import UUID
from datetime import datetime

from ..connection import RDBAsyncConnectionConfig
from ..errors import DuplicatedContentError
from ..schema import FileInfo, FileStatus, Base

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
                "uploaded_at": datetime.now(),
                "error_code": None,
                "error_message": None,
            }
            async with self._session.begin() as session:
                result = await (
                    session.execute(update(FileInfo).where(FileInfo.id == file_id))
                    .values(**values)
                    .returning(FileInfo)
                )

                return result.scalar_one_or_none()

        except IntegrityError as exc:
            if "content_hash" in str(exc.orig).lower():
                raise DuplicatedContentError
            raise

    async def claim(self, file_id: UUID) -> FileInfo | None:
        async with self._session.begin() as session:
            result: FileInfo = await session.get(FileInfo, file_id)

            if result is None:
                return None

            if result.status in {
                FileStatus.PROCESSING,
                FileStatus.SUCCEED,
            }:
                return None

            task_info = await session.execute(
                update(FileInfo)
                .where(FileInfo.id == file_id)
                .values({"status": FileStatus.QUEUED})
                .returning(FileInfo)
            )

            return task_info
