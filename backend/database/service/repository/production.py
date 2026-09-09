from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.schema import Report


class ReportRepository:
    def __init__(self, config: RDBAsyncConnectionConfig):
        self._session = config.async_session_local
        self._engine = config.async_engine

    async def _bulk_insert(self, rows: dict[str, str]) -> Report | None:
        async with self._session.begin() as session:
            result = await session.execute(
                pg_insert(Report)
                .values(**rows)
                .on_conflict_do_nothing(constraint="source_unique")
                .returning(Report)
            )
        return result.scalar_one_or_none()