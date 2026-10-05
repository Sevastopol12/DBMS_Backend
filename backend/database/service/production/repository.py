from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.service.production.schema import ReviewRecord, SystemReport
from backend.domain.processing.models import ReportRow
from backend.timezone import ensure_vietnam_aware, now_vietnam

_CHUNK_SIZE = 500


@dataclass
class BulkInsertResult:
    attempted: int
    inserted: int
    skipped: int  # idempotent duplicates


@dataclass(frozen=True)
class ReviewInput:
    """Database-level type; keeps the database module free of domain imports.

    ``disposition`` is "ACCEPTED_WITH_FLAGS" or "REJECTED".
    """

    source_row_number: int
    disposition: str
    issue_codes: list[str] = field(default_factory=list)


@dataclass
class ReplaceResult:
    attempted: int
    inserted: int
    reviews_inserted: int
    deleted_reports: int
    deleted_reviews: int


def _validate_row_numbers(
    rows: Sequence[ReportRow], source_row_numbers: Sequence[int]
) -> list[int]:
    row_numbers = list(source_row_numbers)
    if len(row_numbers) != len(rows):
        raise ValueError("source_row_numbers must match rows")
    if any(not isinstance(rn, int) or rn < 2 for rn in row_numbers):
        raise ValueError("source_row_numbers must be spreadsheet data row numbers")
    if len(set(row_numbers)) != len(row_numbers):
        raise ValueError("source_row_numbers must be unique")
    return row_numbers


def _build_report_values(
    rows: Sequence[ReportRow],
    row_numbers: list[int],
    source_file_id: UUID,
    facility_id: UUID,
    source_size_bytes: int | None,
) -> list[dict]:
    """Build insert value dicts, reusing the same logic as bulk_insert."""
    return [
        {
            "source_file_id": source_file_id,
            "source_size_bytes": source_size_bytes,
            "source_row_number": row_numbers[index],
            **{
                f: (
                    ensure_vietnam_aware(getattr(row, f))
                    if f == "ngay_kham" and getattr(row, f) is not None
                    else getattr(row, f)
                )
                for f in ReportRow.model_fields
            },
            "facility_id": facility_id,
            "uploaded_at": now_vietnam(),
        }
        for index, row in enumerate(rows)
    ]


def _chunks(items: list, chunk_size: int):
    for i in range(0, len(items), chunk_size):
        yield items[i : i + chunk_size]


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
                **{
                    field: (
                        ensure_vietnam_aware(getattr(row, field))
                        if field == "ngay_kham" and getattr(row, field) is not None
                        else getattr(row, field)
                    )
                    for field in ReportRow.model_fields
                },
                "facility_id": facility_id,
                "uploaded_at": now_vietnam(),
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

    async def replace_file_result(
        self,
        *,
        source_file_id: UUID,
        facility_id: UUID,
        rows: Sequence[ReportRow],
        source_row_numbers: Sequence[int],
        reviews: Sequence[ReviewInput],
        source_size_bytes: int | None = None,
    ) -> ReplaceResult:

        row_numbers = _validate_row_numbers(rows, source_row_numbers)
        report_values = _build_report_values(
            rows, row_numbers, source_file_id, facility_id, source_size_bytes
        )
        review_values = [
            {
                "source_file_id": source_file_id,
                "source_row_number": rv.source_row_number,
                "disposition": rv.disposition,
                "issue_codes": rv.issue_codes,
            }
            for rv in reviews
        ]

        async with self._session.begin() as session:
            # Step 1: delete old report rows
            del_reports = await session.execute(
                delete(SystemReport)
                .where(SystemReport.source_file_id == source_file_id)
                .returning(SystemReport.id)
            )
            deleted_reports = len(del_reports.fetchall())

            # Step 2: delete old review rows
            del_reviews = await session.execute(
                delete(ReviewRecord)
                .where(ReviewRecord.source_file_id == source_file_id)
                .returning(ReviewRecord.id)
            )
            deleted_reviews = len(del_reviews.fetchall())

            # Step 3: insert report rows in chunks (no ON CONFLICT — rows were
            # just deleted; a constraint violation means a concurrent insert)
            inserted_reports = 0
            for chunk in _chunks(report_values, _CHUNK_SIZE):
                res = await session.execute(
                    insert(SystemReport).returning(SystemReport.id),
                    chunk,
                )
                inserted_reports += len(res.fetchall())

            # Step 4: insert review rows in chunks (created_at is server default)
            inserted_reviews = 0
            for chunk in _chunks(review_values, _CHUNK_SIZE):
                res = await session.execute(
                    insert(ReviewRecord).returning(ReviewRecord.id),
                    chunk,
                )
                inserted_reviews += len(res.fetchall())

        return ReplaceResult(
            attempted=len(rows),
            inserted=inserted_reports,
            reviews_inserted=inserted_reviews,
            deleted_reports=deleted_reports,
            deleted_reviews=deleted_reviews,
        )

    async def purge_file(self, source_file_id: UUID) -> tuple[int, int]:
        """Delete all report and review rows for a file.

        Returns ``(deleted_reports, deleted_reviews)``.
        """
        async with self._session.begin() as session:
            del_reports = await session.execute(
                delete(SystemReport)
                .where(SystemReport.source_file_id == source_file_id)
                .returning(SystemReport.id)
            )
            deleted_reports = len(del_reports.fetchall())

            del_reviews = await session.execute(
                delete(ReviewRecord)
                .where(ReviewRecord.source_file_id == source_file_id)
                .returning(ReviewRecord.id)
            )
            deleted_reviews = len(del_reviews.fetchall())

        return (deleted_reports, deleted_reviews)

    async def count_for_file(self, source_file_id: UUID) -> tuple[int, int]:
        """Return ``(report_rows, review_rows)`` for a given file."""
        async with self._session.begin() as session:
            report_result = await session.execute(
                select(func.count())
                .select_from(SystemReport)
                .where(SystemReport.source_file_id == source_file_id)
            )
            report_count = report_result.scalar_one()

            review_result = await session.execute(
                select(func.count())
                .select_from(ReviewRecord)
                .where(ReviewRecord.source_file_id == source_file_id)
            )
            review_count = review_result.scalar_one()

        return (report_count, review_count)


__all__ = [
    "BulkInsertResult",
    "ReplaceResult",
    "ReportRepository",
    "ReviewInput",
]
