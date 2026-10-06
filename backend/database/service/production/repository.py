from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.service.production.schema import Demographic, ReviewRecord


class AcceptedDataRepository:
    """Count rows owned by one source file."""

    def __init__(self, config: RDBAsyncConnectionConfig) -> None:
        self._sessions = config.async_session_local

    async def count_for_file(self, source_file_id: UUID) -> tuple[int, int]:
        """Return ``(records, reviews)`` owned by ``source_file_id``."""

        async with self._sessions() as session:
            records = (
                await session.execute(
                    select(func.count())
                    .select_from(Demographic)
                    .where(Demographic.source_file_id == source_file_id)
                )
            ).scalar_one()
            reviews = (
                await session.execute(
                    select(func.count())
                    .select_from(ReviewRecord)
                    .where(ReviewRecord.source_file_id == source_file_id)
                )
            ).scalar_one()
            return int(records), int(reviews)


__all__ = ["AcceptedDataRepository"]
