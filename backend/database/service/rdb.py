import logging

from sqlalchemy import select, exists
from sqlalchemy.schema import CreateSchema
from datetime import datetime

from ..connection import RDBAsyncConnectionConfig
from ..errors import FileDuplicatedError
from ..schema import FileInfo, FileStatus, Base

logger = logging.getLogger(__name__)


class RDBService:
    def __init__(self, config: RDBAsyncConnectionConfig):
        self.config = config

    async def create_table_and_schema(self, orm_object: Base) -> bool:
        async with self.config.engine.begin() as connection:
            await connection.execute(
                CreateSchema(orm_object.__table__.schema, if_not_exists=True)
            )
            await connection.run_sync(orm_object.__table__.create, checkfirst=True)

        return 1

    async def record(self, filename: str, file_hash: str) -> dict[str, str]:
        if await self._is_existed(file_hash):
            raise FileDuplicatedError(filename, file_hash)

        async with self.config.async_session_local.begin() as session:
            record_info = FileInfo(
                filename=filename,
                file_hashed=file_hash,
                uploaded_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=FileStatus.PENDING,
            )
            session.add(record_info)

        return {
            "filename": record_info.filename,
            "created_at": record_info.uploaded_date,
            "location": f"{record_info.__table__.schema}/{record_info.__tablename__}",
        }

    async def _is_existed(self, hashed_file_content: str) -> bool:
        async with self.config.async_session_local.begin() as session:
            statement = select(
                exists().where(FileInfo.file_hashed == hashed_file_content)
            )
            result = await session.execute(statement)

            return result.scalar()

    