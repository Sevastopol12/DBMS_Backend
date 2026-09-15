from __future__ import annotations
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.schema import SystemReport
from backend.domain.ingestion.contracts import ReportRow

@dataclass
class BulkInsertResult:
    attempted: int
    inserted: int
    skipped: int   # idempotent duplicates

class ReportRepository:
    def __init__(self, config: RDBAsyncConnectionConfig) -> None:
        self._session = config.async_session_local
        self._engine = config.async_engine

    async def bulk_insert(
        self,
        rows: Sequence[ReportRow],
        source_file_id: UUID,
        source_size_bytes: int | None = None,
    ) -> BulkInsertResult:
        """Bulk-insert accepted ReportRows into SystemReport.
        
        Uses PostgreSQL INSERT ... ON CONFLICT DO NOTHING on the source_unique constraint.
        Returns counts of attempted, inserted, and idempotently skipped rows.
        """
        if not rows:
            return BulkInsertResult(attempted=0, inserted=0, skipped=0)

        values = [
            {
                "source_file_id": source_file_id,
                "source_size_bytes": source_size_bytes,
                **{field: getattr(row, field) for field in row.model_fields},
            }
            for row in rows
        ]
        async with self._session.begin() as session:
            result = await session.execute(
                pg_insert(SystemReport)
                .values(values)
                .on_conflict_do_nothing(constraint="source_unique")
                .returning(SystemReport.id)
            )
            inserted_count = len(result.fetchall())

        return BulkInsertResult(
            attempted=len(rows),
            inserted=inserted_count,
            skipped=len(rows) - inserted_count,
        )
