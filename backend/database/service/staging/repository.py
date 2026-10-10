from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from backend.database.base import Base
from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.errors import (
    DuplicatedContentError,
    is_duplicate_content_integrity_error,
)
from backend.database.service.staging.schema import FileInfo
from backend.domain.processing.models import FileStatus
from backend.timezone import now_vietnam

_REQUEUEABLE = {FileStatus.ERROR, FileStatus.SUCCEED}
_CHUNK_SIZE = 1_000
_ALLOWED_FILTER_STATUSES = {
    FileStatus.QUEUED,
    FileStatus.ERROR,
    FileStatus.SUCCEED,
    FileStatus.REJECTED,
}


@dataclass
class RequeueResult:
    requeued: list[UUID] = field(default_factory=list)
    already_queued: list[UUID] = field(default_factory=list)
    skipped: dict[UUID, str] = field(default_factory=dict)


def _chunks(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


class IngestionRepository:
    def __init__(self, config: RDBAsyncConnectionConfig):
        self._session = config.async_session_local
        self._engine = config.async_engine

    async def create_table_and_schema(self, orm_object: Base) -> bool:
        from sqlalchemy.schema import CreateSchema

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

    # Upload lifecycle

    async def complete_upload(
        self,
        file_id: UUID,
        content_hash: str,
        size_bytes: int,
        mappings: dict[str, object] | None,
    ) -> FileInfo | None:
        """Set status=QUEUED and queued_at=now (CONTRACTS §4)."""
        try:
            now = now_vietnam()
            values = {
                "content_hash": content_hash,
                "size_bytes": size_bytes,
                "status": FileStatus.QUEUED,
                "mappings": mappings,
                "uploaded_at": now,
                "queued_at": now,
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
        """Atomically claim queued work or reclaim stale PROCESSING work.

        Also increments attempt_count (CONTRACTS §4 / plan.md D4).
        """
        now = now_vietnam()
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
                        "attempt_count": FileInfo.attempt_count + 1,
                    }
                )
                .returning(FileInfo.object_key, FileInfo.mappings)
            )
            row = result.one_or_none()
        return (row.object_key, row.mappings) if row is not None else None

    async def recover_processing(
        self, *, processing_timeout: timedelta = timedelta(minutes=15)
    ) -> list[UUID]:
        """Reclaim stale PROCESSING rows → QUEUED, set queued_at=now (CONTRACTS §4)."""
        now = now_vietnam()
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
                .values(
                    {"status": FileStatus.QUEUED, "started_at": None, "queued_at": now}
                )
                .returning(FileInfo.id)
            )
            return list(result.scalars().all())

    async def requeue(
        self,
        *,
        file_ids: Sequence[UUID] | None = None,
        statuses: Sequence[str] | None = None,
        allow_rejected: bool = False,
    ) -> RequeueResult:
        """Atomically requeue files to QUEUED (CONTRACTS §4).

        Rules:
        - At least one of file_ids / statuses else ValueError.
        - statuses may only contain QUEUED, ERROR, SUCCEED, REJECTED else ValueError.
        - Requeueable: ERROR, SUCCEED, plus REJECTED if allow_rejected.
        - Does NOT touch attempt_count, error_code, error_message.
        - Chunks id lists (1 000 per statement).
        """
        if file_ids is None and statuses is None:
            raise ValueError("At least one of file_ids or statuses must be provided.")

        if statuses is not None:
            bad = set(statuses) - _ALLOWED_FILTER_STATUSES
            if bad:
                raise ValueError(
                    f"Invalid statuses for requeue filter: {bad}. "
                    f"Allowed: {_ALLOWED_FILTER_STATUSES}"
                )

        requeueable = set(_REQUEUEABLE)
        if allow_rejected:
            requeueable.add(FileStatus.REJECTED)

        now = now_vietnam()
        result = RequeueResult()

        if file_ids is not None:
            id_list = list(file_ids)

            # 1. Resolve current states for the requested ids.
            fetched: dict[UUID, str] = {}
            for chunk in _chunks(id_list, _CHUNK_SIZE):
                async with self._session.begin() as session:
                    rows = await session.execute(
                        select(FileInfo.id, FileInfo.status).where(
                            FileInfo.id.in_(chunk)
                        )
                    )
                    for row in rows:
                        fetched[row.id] = row.status

            # 2. Categorise each requested id.
            to_update: list[UUID] = []
            for fid in id_list:
                if fid not in fetched:
                    result.skipped[fid] = "NOT_FOUND"
                    continue
                status = fetched[fid]
                if status == FileStatus.QUEUED:
                    result.already_queued.append(fid)
                elif status == FileStatus.PROCESSING:
                    result.skipped[fid] = "PROCESSING"
                elif status == FileStatus.CREATED:
                    result.skipped[fid] = "CREATED"
                elif status == FileStatus.REJECTED and not allow_rejected:
                    result.skipped[fid] = "REJECTED_REQUIRES_FORCE"
                elif status in requeueable:
                    to_update.append(fid)
                else:
                    result.skipped[fid] = "CREATED"

            # Apply status filter if given (intersection).
            if statuses is not None:
                status_set = set(statuses)
                narrowed: list[UUID] = []
                for fid in to_update:
                    if fetched[fid] in status_set:
                        narrowed.append(fid)
                    else:
                        result.skipped[fid] = "STATE_CHANGED"
                to_update = narrowed

            # 3. UPDATE in chunks; detect races via RETURNING.
            for chunk in _chunks(to_update, _CHUNK_SIZE):
                async with self._session.begin() as session:
                    res = await session.execute(
                        update(FileInfo)
                        .where(
                            FileInfo.id.in_(chunk),
                            FileInfo.status.in_(list(requeueable)),
                        )
                        .values(
                            status=FileStatus.QUEUED,
                            queued_at=now,
                            started_at=None,
                        )
                        .returning(FileInfo.id)
                    )
                    changed = set(res.scalars().all())
                    for fid in chunk:
                        if fid in changed:
                            result.requeued.append(fid)
                        else:
                            # Race — someone else changed the status.
                            result.skipped[fid] = "STATE_CHANGED"

        else:
            # statuses-only selection — no skip reporting, just do the UPDATE.
            assert statuses is not None
            effective = set(statuses) & requeueable
            if not effective:
                return result
            async with self._session.begin() as session:
                res = await session.execute(
                    update(FileInfo)
                    .where(FileInfo.status.in_(list(effective)))
                    .values(
                        status=FileStatus.QUEUED,
                        queued_at=now,
                        started_at=None,
                    )
                    .returning(FileInfo.id)
                )
                result.requeued.extend(res.scalars().all())

        return result

    async def requeue_retryable_errors(self, *, max_attempts: int) -> list[UUID]:
        """ERROR with 1 <= attempt_count < max_attempts → QUEUED (CONTRACTS §4)."""
        now = now_vietnam()
        async with self._session.begin() as session:
            result = await session.execute(
                update(FileInfo)
                .where(
                    FileInfo.status == FileStatus.ERROR,
                    FileInfo.attempt_count >= 1,
                    FileInfo.attempt_count < max_attempts,
                )
                .values(status=FileStatus.QUEUED, queued_at=now, started_at=None)
                .returning(FileInfo.id)
            )
            return list(result.scalars().all())

    async def count_exhausted_errors(self, *, max_attempts: int) -> int:
        """Count ERROR rows with attempt_count >= max_attempts (CONTRACTS §4)."""
        async with self._session.begin() as session:
            result = await session.execute(
                select(func.count()).where(
                    FileInfo.status == FileStatus.ERROR,
                    FileInfo.attempt_count >= max_attempts,
                )
            )
            return result.scalar_one()

    async def list_stale_queued(self, *, older_than: timedelta) -> list[UUID]:
        """QUEUED rows with queued_at IS NULL or queued_at <= now - older_than (CONTRACTS §4)."""
        cutoff: datetime = now_vietnam() - older_than
        async with self._session.begin() as session:
            result = await session.execute(
                select(FileInfo.id).where(
                    FileInfo.status == FileStatus.QUEUED,
                    or_(
                        FileInfo.queued_at.is_(None),
                        FileInfo.queued_at <= cutoff,
                    ),
                )
            )
            return list(result.scalars().all())

    #
    # Read side (ops dashboard)
    #

    async def status_counts(self, *, facility_id: UUID | None = None) -> dict[str, int]:
        stmt = select(FileInfo.status, func.count().label("n")).group_by(
            FileInfo.status
        )
        if facility_id is not None:
            stmt = stmt.where(FileInfo.facility_id == facility_id)
        async with self._session.begin() as session:
            result = await session.execute(stmt)
            return {row.status: row.n for row in result}

    async def error_code_counts(
        self, *, status: str, facility_id: UUID | None = None
    ) -> dict[str, int]:
        stmt = (
            select(FileInfo.error_code, func.count().label("n"))
            .where(FileInfo.status == status)
            .group_by(FileInfo.error_code)
        )
        if facility_id is not None:
            stmt = stmt.where(FileInfo.facility_id == facility_id)
        async with self._session.begin() as session:
            result = await session.execute(stmt)
            return {(row.error_code or ""): row.n for row in result}

    async def retry_buckets(
        self, *, max_attempts: int, facility_id: UUID | None = None
    ) -> dict[str, int]:
        """{"retryable", "exhausted", "api_failed"} counts for ERROR rows."""
        base = select(FileInfo.attempt_count).where(FileInfo.status == FileStatus.ERROR)
        if facility_id is not None:
            base = base.where(FileInfo.facility_id == facility_id)

        async with self._session.begin() as session:
            result = await session.execute(base)
            counts = result.scalars().all()

        retryable = sum(1 for c in counts if 1 <= c < max_attempts)
        exhausted = sum(1 for c in counts if c >= max_attempts)
        api_failed = sum(1 for c in counts if c == 0)
        return {
            "retryable": retryable,
            "exhausted": exhausted,
            "api_failed": api_failed,
        }

    async def oldest_queued_at(self) -> datetime | None:
        async with self._session.begin() as session:
            result = await session.execute(
                select(func.min(FileInfo.queued_at)).where(
                    FileInfo.status == FileStatus.QUEUED
                )
            )
            return result.scalar_one_or_none()

    async def last_completed_at(
        self, *, facility_id: UUID | None = None
    ) -> datetime | None:
        stmt = select(func.max(FileInfo.completed_at)).where(
            FileInfo.status == FileStatus.SUCCEED
        )
        if facility_id is not None:
            stmt = stmt.where(FileInfo.facility_id == facility_id)
        async with self._session.begin() as session:
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_files(
        self,
        *,
        status: str | None = None,
        error_code: str | None = None,
        facility_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        stmt = select(FileInfo).order_by(FileInfo.created_at.desc())
        if status is not None:
            stmt = stmt.where(FileInfo.status == status)
        if error_code is not None:
            stmt = stmt.where(FileInfo.error_code == error_code)
        if facility_id is not None:
            stmt = stmt.where(FileInfo.facility_id == facility_id)
        stmt = stmt.limit(limit).offset(offset)

        async with self._session.begin() as session:
            result = await session.execute(stmt)
            return [_file_to_dict(row) for row in result.scalars().all()]

    async def get_detail(self, file_id: UUID) -> dict | None:
        async with self._session.begin() as session:
            row = await session.get(FileInfo, file_id)
            if row is None:
                return None
            d = _file_to_dict(row)
            d["quality_report"] = row.quality_report
            return d

    #
    # Rejection artifact + facility-scoped lineage (WP-06, migration 011)
    #

    async def set_artifact(
        self, file_id: UUID, key: str, expires_at: datetime
    ) -> FileInfo | None:
        """Record the rejection artifact object key and its expiry."""
        async with self._session.begin() as session:
            result = await session.execute(
                update(FileInfo)
                .where(FileInfo.id == file_id)
                .values(
                    rejection_artifact_key=key,
                    rejection_artifact_expires_at=expires_at,
                )
                .returning(FileInfo)
            )
            return result.scalar_one_or_none()

    async def clear_artifact(self, file_id: UUID) -> FileInfo | None:
        """Forget the rejection artifact columns after the object is deleted."""
        async with self._session.begin() as session:
            result = await session.execute(
                update(FileInfo)
                .where(FileInfo.id == file_id)
                .values(
                    rejection_artifact_key=None,
                    rejection_artifact_expires_at=None,
                )
                .returning(FileInfo)
            )
            return result.scalar_one_or_none()

    async def get_for_facility(
        self, file_id: UUID, facility_id: UUID
    ) -> FileInfo | None:
        """Fetch one file only when it belongs to ``facility_id`` (SQL-filtered)."""
        async with self._session.begin() as session:
            result = await session.execute(
                select(FileInfo).where(
                    FileInfo.id == file_id,
                    FileInfo.facility_id == facility_id,
                )
            )
            return result.scalar_one_or_none()

    async def list_for_facility(
        self,
        facility_id: UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FileInfo]:
        """List files of one facility, newest first (SQL-filtered)."""
        stmt = (
            select(FileInfo)
            .where(FileInfo.facility_id == facility_id)
            .order_by(FileInfo.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(FileInfo.status == status)
        stmt = stmt.limit(limit).offset(offset)
        async with self._session.begin() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_expired_artifacts(
        self, now: datetime, limit: int = 1_000
    ) -> list[FileInfo]:
        """Files whose artifact key is set and whose expiry is at or past ``now``."""
        async with self._session.begin() as session:
            result = await session.execute(
                select(FileInfo)
                .where(
                    FileInfo.rejection_artifact_key.is_not(None),
                    FileInfo.rejection_artifact_expires_at <= now,
                )
                .order_by(FileInfo.rejection_artifact_expires_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())


def _file_to_dict(row: FileInfo) -> dict:
    """Project a FileInfo row to the list_files dict shape (CONTRACTS §4)."""
    return {
        "id": row.id,
        "filename": row.filename,
        "facility_id": row.facility_id,
        "status": row.status,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "attempt_count": row.attempt_count,
        "created_at": row.created_at,
        "queued_at": row.queued_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "last_error_at": row.last_error_at,
        "accepted_row_count": row.accepted_row_count,
        "rejected_row_count": row.rejected_row_count,
        "size_bytes": row.size_bytes,
    }


__all__ = ["IngestionRepository", "RequeueResult"]
