from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.service.production.schema import SystemReport
from backend.domain.processing.models import ReportRow


@dataclass
class BulkInsertResult:
    attempted: int
    inserted: int
    skipped: int  # idempotent duplicates


class ReportRepository:
    def __init__(self, config: RDBAsyncConnectionConfig) -> None:
        self._session = config.async_session_local
        self._engine = config.async_engine

    async def bulk_insert(
        self,
        rows: Sequence[ReportRow],
        source_file_id: UUID,
        facility_id: UUID,
        source_size_bytes: int | None = None,
        source_row_numbers: Sequence[int] | None = None,
    ) -> BulkInsertResult:
        """Bulk-insert accepted ReportRows into SystemReport."""
        if not rows:
            return BulkInsertResult(attempted=0, inserted=0, skipped=0)

        if source_row_numbers is None:
            raise ValueError(
                "source_row_numbers is required; persistence cannot infer source rows"
            )

        row_numbers = list(source_row_numbers)
        if len(row_numbers) != len(rows):
            raise ValueError("source_row_numbers must match rows")
        if any(
            not isinstance(row_number, int) or row_number < 2
            for row_number in row_numbers
        ):
            raise ValueError("source_row_numbers must be spreadsheet data row numbers")
        if len(set(row_numbers)) != len(row_numbers):
            raise ValueError("source_row_numbers must be unique")

        values = [
            {
                "source_file_id": source_file_id,
                "source_size_bytes": source_size_bytes,
                "source_row_number": row_numbers[index],
                **{field: getattr(row, field) for field in ReportRow.model_fields},
                "facility_id": facility_id,
            }
            for index, row in enumerate(rows)
        ]
        async with self._session.begin() as session:
            result = await session.execute(
                pg_insert(SystemReport)
                .values(values)
                .on_conflict_do_nothing(constraint="source_row_unique")
                .returning(SystemReport.id)
            )
            inserted_count = len(result.fetchall())

        return BulkInsertResult(
            attempted=len(rows),
            inserted=inserted_count,
            skipped=len(rows) - inserted_count,
        )


__all__ = ["BulkInsertResult", "ReportRepository"]
