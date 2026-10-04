"""WorkflowRunRepository — CONTRACTS §5."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, insert, select, update

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.service.staging.workflow_schema import WorkflowRunLog
from backend.timezone import now_vietnam


def _row_to_dict(row) -> dict:
    """Convert a WorkflowRunLog ORM row to a plain dict with Python types."""
    return {
        "id": row.id,
        "workflow_type": row.workflow_type,
        "trigger_type": row.trigger_type,
        "status": row.status,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "items_seen": row.items_seen,
        "items_dispatched": row.items_dispatched,
        "items_skipped": row.items_skipped,
        "items_failed": row.items_failed,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "details": row.details,
        "celery_task_id": row.celery_task_id,
        "computation_run_id": row.computation_run_id,
    }


def _mapping_to_dict(mapping) -> dict:
    """Convert a SQLAlchemy RowMapping to a plain dict."""
    return dict(mapping)


class WorkflowRunRepository:
    """Lifecycle repository for workflow_run_log rows (CONTRACTS §5)."""

    def __init__(self, config: RDBAsyncConnectionConfig) -> None:
        self._session = config.async_session_local

    async def start(
        self,
        workflow_type: str,
        trigger_type: str,
        *,
        celery_task_id: str | None = None,
    ) -> UUID:
        """Insert a RUNNING row and return its id."""
        now = now_vietnam()
        async with self._session.begin() as session:
            result = await session.execute(
                insert(WorkflowRunLog)
                .values(
                    workflow_type=workflow_type,
                    trigger_type=trigger_type,
                    status="RUNNING",
                    started_at=now,
                    celery_task_id=celery_task_id,
                    details={},
                )
                .returning(WorkflowRunLog.id)
            )
            return result.scalar_one()

    async def finish(
        self,
        run_id: UUID,
        status: str,
        *,
        items_seen: int = 0,
        items_dispatched: int = 0,
        items_skipped: int = 0,
        items_failed: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
        details: dict | None = None,
        computation_run_id: UUID | None = None,
    ) -> bool:
        """UPDATE … WHERE id=run_id AND status='RUNNING'. Returns True if a row changed."""
        now = now_vietnam()
        values: dict = {
            "status": status,
            "finished_at": now,
            "items_seen": items_seen,
            "items_dispatched": items_dispatched,
            "items_skipped": items_skipped,
            "items_failed": items_failed,
            "details": details if details is not None else {},
        }
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message
        if computation_run_id is not None:
            values["computation_run_id"] = computation_run_id

        async with self._session.begin() as session:
            result = await session.execute(
                update(WorkflowRunLog)
                .where(
                    WorkflowRunLog.id == run_id,
                    WorkflowRunLog.status == "RUNNING",
                )
                .values(**values)
            )
            return result.rowcount > 0

    async def reap_stale(self, *, max_age: timedelta = timedelta(hours=1)) -> int:
        """Mark RUNNING rows older than max_age as FAILED with error_code='STALE_RUN'."""
        now = now_vietnam()
        cutoff: datetime = now - max_age
        async with self._session.begin() as session:
            result = await session.execute(
                update(WorkflowRunLog)
                .where(
                    WorkflowRunLog.status == "RUNNING",
                    WorkflowRunLog.started_at <= cutoff,
                )
                .values(
                    status="FAILED",
                    finished_at=now,
                    error_code="STALE_RUN",
                    error_message="STALE_RUN",
                )
            )
            return result.rowcount

    async def recent(
        self,
        *,
        workflow_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        stmt = select(WorkflowRunLog).order_by(WorkflowRunLog.started_at.desc())
        if workflow_type is not None:
            stmt = stmt.where(WorkflowRunLog.workflow_type == workflow_type)
        stmt = stmt.limit(limit).offset(offset)
        async with self._session.begin() as session:
            result = await session.execute(stmt)
            return [_row_to_dict(row) for row in result.scalars().all()]

    async def get(self, run_id: UUID) -> dict | None:
        async with self._session.begin() as session:
            row = await session.get(WorkflowRunLog, run_id)
            return _row_to_dict(row) if row is not None else None

    async def latest_by_type(self) -> dict[str, dict]:
        """Return the newest run dict per workflow_type."""
        stmt = (
            select(WorkflowRunLog).order_by(WorkflowRunLog.started_at.desc()).limit(500)
        )
        async with self._session.begin() as session:
            result = await session.execute(stmt)
            seen: dict[str, dict] = {}
            for row in result.scalars().all():
                if row.workflow_type not in seen:
                    seen[row.workflow_type] = _row_to_dict(row)
            return seen

    async def prune(self, *, older_than: timedelta) -> int:
        """Delete finished (non-RUNNING) rows whose finished_at < now - older_than."""
        cutoff: datetime = now_vietnam() - older_than
        async with self._session.begin() as session:
            result = await session.execute(
                delete(WorkflowRunLog).where(
                    WorkflowRunLog.status != "RUNNING",
                    WorkflowRunLog.finished_at < cutoff,
                )
            )
            return result.rowcount


__all__ = ["WorkflowRunRepository"]
