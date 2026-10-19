from __future__ import annotations

import asyncio
import itertools
import logging
import os
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.service.production.schema import (
    DEMOGRAPHIC_FIELDS,
    MEASUREMENT_FIELDS,
    Demographic,
    Measurement,
    ReviewRecord,
)

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 500
_MAX_ATTEMPTS = 3
_KEY_COLUMNS = frozenset({"facility_id", "cccd", "ngay_kham"})

_DISPOSITIONS = frozenset({"ACCEPTED", "REJECTED"})


@dataclass(frozen=True)
class PersistRecord:
    values: Mapping[str, Any]  # canonical fields incl. cccd, ngay_kham


@dataclass(frozen=True)
class PersistReview:
    source_row_number: int
    disposition: str
    duplicate_role: str
    merged_into_row: int | None
    group_row_numbers: Sequence[int]
    issue_codes: Sequence[str]


@dataclass(frozen=True)
class PersistRequest:
    source_file_id: UUID
    facility_id: UUID
    source_filename: str
    source_file_uploaded_at: datetime
    transformed_at: datetime
    records: Sequence[PersistRecord]
    reviews: Sequence[PersistReview]


@dataclass(frozen=True)
class PersistResult:
    attempted: int
    applied: int
    superseded: int
    released: int
    reviews_written: int


def _statement_timeout_ms() -> int:
    raw = os.getenv("PERSIST_STATEMENT_TIMEOUT_MS", "60000")
    return int(raw)


def _is_deadlock(exc: BaseException) -> bool:
    """Return True when the exception chain carries SQLSTATE 40P01.

    SQLAlchemy wraps the asyncpg driver error in ``DBAPIError`` (``.orig``),
    so the whole ``orig`` / ``__cause__`` / ``__context__`` chain is walked
    instead of matching on a single guessed type.
    """

    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if getattr(current, "sqlstate", None) == "40P01":
            return True
        for attr in ("orig", "__cause__", "__context__"):
            nxt = getattr(current, attr, None)
            if isinstance(nxt, BaseException):
                stack.append(nxt)
    return False


def _chunks(items: Sequence[Any], size: int) -> Sequence[Sequence[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _require_truncated(ngay_kham: Any) -> None:
    if not isinstance(ngay_kham, datetime):
        raise ValueError("ngay_kham must be a datetime")  # noqa: TRY004 - contract requires ValueError
    if ngay_kham.tzinfo is None:
        raise ValueError("ngay_kham must be timezone-aware")
    if ngay_kham.microsecond != 0:
        raise ValueError("ngay_kham must already be truncated to whole seconds")


def _validated_entries(
    req: PersistRequest,
) -> list[tuple[str, datetime, Mapping[str, Any]]]:
    """Sort records by key and assert in-request key uniqueness (E-grouping guarantee)."""

    entries: list[tuple[str, datetime, Mapping[str, Any]]] = []
    for record in req.records:
        values = record.values
        cccd = values.get("cccd")
        ngay_kham = values.get("ngay_kham")

        if not isinstance(cccd, str) or not cccd:
            raise ValueError("each record must carry a non-empty cccd")

        _require_truncated(ngay_kham)
        entries.append((cccd, ngay_kham, values))

    entries.sort(key=lambda item: (item[0], item[1]))

    for prev, cur in itertools.pairwise(entries):
        if (prev[0], prev[1]) == (cur[0], cur[1]):
            raise ValueError("duplicate logical key inside one persist request")

    for review in req.reviews:
        if review.source_row_number < 2:
            raise ValueError("review source_row_number must be >= 2")
        if review.disposition not in _DISPOSITIONS:
            raise ValueError("review disposition must be ACCEPTED or REJECTED")

    return entries


class AcceptedDataPersistence:
    """Own the one-transaction persist/release boundary for accepted data."""

    def __init__(self, config: RDBAsyncConnectionConfig) -> None:
        self._sessions = config.async_session_local

    async def persist(self, req: PersistRequest) -> PersistResult:
        entries = _validated_entries(req)
        attempt = 0
        while True:
            attempt += 1
            try:
                async with self._sessions() as session, session.begin():
                    return await self._run_tx(session, req, entries)
            except Exception as exc:
                if _is_deadlock(exc) and attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(random.uniform(0.05, 0.2) * attempt)
                    continue
                raise

    async def _run_tx(
        self,
        session: Any,
        req: PersistRequest,
        entries: Sequence[tuple[str, datetime, Mapping[str, Any]]],
    ) -> PersistResult:
        timeout_ms = _statement_timeout_ms()
        await session.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
        await session.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended(CAST(:fid AS text), 0))"
            ),
            {"fid": str(req.source_file_id)},
        )

        owned_before = await self._owned_keys(session, req.source_file_id)

        owned_demographic_cccds = await self._owned_demographic_cccds(
            session, req.source_file_id
        )
        earliest_by_cccd: dict[str, tuple[datetime, Mapping[str, Any]]] = {}
        for cccd, ngay_kham, values in entries:
            if cccd not in earliest_by_cccd or ngay_kham < earliest_by_cccd[cccd][0]:
                earliest_by_cccd[cccd] = (ngay_kham, values)
        demographic_rows = [
            self._demographic_row(req, values) for _, values in earliest_by_cccd.values()
        ]
        await self._upsert_demographics(session, demographic_rows)
        attempted = len(entries)

        measurement_rows = [
            self._measurement_row(req, values) for _, _, values in entries
        ]
        applied = await self._upsert_measurements(session, measurement_rows)

        run_keys = {(cccd, ngay_kham) for cccd, ngay_kham, _ in entries}
        released = await self._delete_stale(
            session,
            req.source_file_id,
            owned_before,
            run_keys,
            owned_demographic_cccds,
            set(earliest_by_cccd),
        )
        reviews_written = await self._rewrite_reviews(session, req)

        result = PersistResult(
            attempted=attempted,
            applied=applied,
            superseded=attempted - applied,
            released=released,
            reviews_written=reviews_written,
        )
        logger.info(
            "persist file_id=%s attempted=%d applied=%d superseded=%d released=%d reviews=%d",
            req.source_file_id,
            result.attempted,
            result.applied,
            result.superseded,
            result.released,
            result.reviews_written,
        )
        return result

    async def release_file(self, source_file_id: UUID) -> int:
        """Delete rows owned by a file and unreferenced demographics; return count."""

        attempt = 0
        while True:
            attempt += 1
            try:
                async with self._sessions() as session, session.begin():
                    timeout_ms = _statement_timeout_ms()
                    await session.execute(
                        text(f"SET LOCAL statement_timeout = {timeout_ms}")
                    )
                    await session.execute(
                        text(
                            "SELECT pg_advisory_xact_lock(hashtextextended(CAST(:fid AS text), 0))"
                        ),
                        {"fid": str(source_file_id)},
                    )
                    await session.execute(
                        delete(ReviewRecord).where(
                            ReviewRecord.source_file_id == source_file_id
                        )
                    )
                    await session.execute(
                        delete(Measurement).where(
                            Measurement.source_file_id == source_file_id
                        )
                    )
                    result = await session.execute(
                        delete(Demographic).where(
                            Demographic.source_file_id == source_file_id,
                            ~exists(
                                select(Measurement.id).where(
                                    Measurement.facility_id == Demographic.facility_id,
                                    Measurement.cccd == Demographic.cccd,
                                )
                            ),
                        )
                    )
                    released = int(result.rowcount or 0)
                    logger.info(
                        "release_file file_id=%s released=%d",
                        source_file_id,
                        released,
                    )
                    return released
            except Exception as exc:
                if _is_deadlock(exc) and attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(random.uniform(0.05, 0.2) * attempt)
                    continue
                raise

    async def _owned_keys(
        self, session: Any, source_file_id: UUID
    ) -> set[tuple[str, datetime]]:
        result = await session.execute(
            select(Measurement.cccd, Measurement.ngay_kham).where(
                Measurement.source_file_id == source_file_id
            )
        )
        return {(row[0], row[1]) for row in result.all()}

    async def _owned_demographic_cccds(
        self, session: Any, source_file_id: UUID
    ) -> set[str]:
        result = await session.execute(
            select(Demographic.cccd).where(Demographic.source_file_id == source_file_id)
        )
        return set(result.scalars().all())

    def _demographic_row(
        self, req: PersistRequest, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "facility_id": req.facility_id,
            "source_file_id": req.source_file_id,
            "source_file_uploaded_at": req.source_file_uploaded_at,
            "uploaded_at": req.transformed_at,
        }
        for field in DEMOGRAPHIC_FIELDS:
            row[field] = values.get(field)
        return row

    def _measurement_row(
        self, req: PersistRequest, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "facility_id": req.facility_id,
            "source_file_id": req.source_file_id,
            "source_file_uploaded_at": req.source_file_uploaded_at,
            "uploaded_at": req.transformed_at,
        }
        for field in MEASUREMENT_FIELDS:
            row[field] = values.get(field)
        return row

    async def _upsert_demographics(
        self, session: Any, rows: list[dict[str, Any]]
    ) -> None:
        for chunk in _chunks(rows, _CHUNK_SIZE):
            stmt = pg_insert(Demographic).values(chunk)
            update_columns = sorted(set(chunk[0]) - {"facility_id", "cccd"})
            stmt = stmt.on_conflict_do_update(
                constraint="demographic_facility_cccd_unique",
                set_={column: stmt.excluded[column] for column in update_columns},
                where=stmt.excluded.ngay_kham < Demographic.ngay_kham,
            )
            await session.execute(stmt)

    async def _upsert_measurements(
        self, session: Any, rows: list[dict[str, Any]]
    ) -> int:
        applied = 0
        for chunk in _chunks(rows, _CHUNK_SIZE):
            update_columns = sorted(set(chunk[0].keys()) - _KEY_COLUMNS)
            stmt = pg_insert(Measurement).values(chunk)
            stmt = stmt.on_conflict_do_update(
                constraint="measurement_visit_unique",
                set_={column: stmt.excluded[column] for column in update_columns},
                where=tuple_(
                    Measurement.source_file_uploaded_at, Measurement.source_file_id
                )
                <= tuple_(
                    stmt.excluded.source_file_uploaded_at,
                    stmt.excluded.source_file_id,
                ),
            ).returning(Measurement.cccd)
            result = await session.execute(stmt)
            applied += len(result.all())
        return applied

    async def _delete_stale(
        self,
        session: Any,
        source_file_id: UUID,
        owned_before: set[tuple[str, datetime]],
        run_keys: set[tuple[str, datetime]],
        owned_demographic_cccds: set[str],
        run_cccds: set[str],
    ) -> int:
        stale = sorted(owned_before - run_keys)
        released = 0
        for chunk in _chunks(stale, _CHUNK_SIZE):
            result = await session.execute(
                delete(Measurement).where(
                    Measurement.source_file_id == source_file_id,
                    tuple_(Measurement.cccd, Measurement.ngay_kham).in_(chunk),
                )
            )
            released += int(result.rowcount or 0)
        stale_cccds = sorted(owned_demographic_cccds - run_cccds)
        for chunk in _chunks(stale_cccds, _CHUNK_SIZE):
            result = await session.execute(
                delete(Demographic).where(
                    Demographic.source_file_id == source_file_id,
                    Demographic.cccd.in_(chunk),
                    ~exists(
                        select(Measurement.id).where(
                            Measurement.facility_id == Demographic.facility_id,
                            Measurement.cccd == Demographic.cccd,
                        )
                    ),
                )
            )
        return released

    async def _rewrite_reviews(self, session: Any, req: PersistRequest) -> int:
        await session.execute(
            delete(ReviewRecord).where(
                ReviewRecord.source_file_id == req.source_file_id
            )
        )
        rows = [
            {
                "source_file_id": req.source_file_id,
                "source_filename": req.source_filename,
                "source_row_number": review.source_row_number,
                "disposition": review.disposition,
                "duplicate_role": review.duplicate_role,
                "merged_into_row": review.merged_into_row,
                "group_row_numbers": list(review.group_row_numbers),
                "issue_codes": list(review.issue_codes),
            }
            for review in req.reviews
        ]
        for chunk in _chunks(rows, _CHUNK_SIZE):
            await session.execute(pg_insert(ReviewRecord).values(chunk))
        return len(rows)


__all__ = [
    "AcceptedDataPersistence",
    "PersistRecord",
    "PersistRequest",
    "PersistResult",
    "PersistReview",
]
