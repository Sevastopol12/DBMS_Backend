from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import Select, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.errors import (
    MetricsRunInProgress,
    MetricsStoreUnavailable,
    is_run_in_progress_integrity_error,
)
from backend.database.service.metrics.schema import (
    ComputationRunLog,
    MetricComorbidityBreakdown,
    MetricDataQualitySummary,
    MetricPeriodSummary,
    PatientCurrentState,
)
from backend.timezone import now_utc

if TYPE_CHECKING:
    from backend.domain.computation.pipeline import ComputationResult


_METRIC_TABLES = (
    (MetricPeriodSummary, "period_summary_rows"),
    (MetricComorbidityBreakdown, "comorbidity_rows"),
    (PatientCurrentState, "patient_state_rows"),
    (MetricDataQualitySummary, "data_quality_rows"),
)

_SCOPING_COLUMNS = frozenset({"id", "run_id"})


def _row_columns(model: Any) -> tuple[Any, ...]:
    return tuple(
        getattr(model, column.key)
        for column in model.__table__.columns
        if column.key not in _SCOPING_COLUMNS
    )


_ROW_COLUMNS = {model: _row_columns(model) for model, _ in _METRIC_TABLES}


def _returned_count(result: Any) -> int:
    rowcount = getattr(result, "rowcount", -1)
    if rowcount is not None and rowcount >= 0:
        return int(rowcount)
    fetchall = getattr(result, "fetchall", None)
    if callable(fetchall):
        return len(fetchall())
    all_rows = getattr(result, "all", None)
    if callable(all_rows):
        return len(all_rows())
    return 0


def _chunks(rows: Iterable[dict], chunk_size: int) -> Iterable[list[dict]]:
    chunk: list[dict] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) == chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


class MetricsRepository:
    """Write run snapshots and read the latest published snapshot.

    ``run_id`` is an intentional diagnostic/test escape hatch: when supplied,
    it selects that run directly and does not require the run to be
    ``SUCCEEDED`` or unpruned. Public API routes do not expose this argument;
    callers that use it must treat the result as historical/debug data.
    """

    def __init__(self, config: RDBAsyncConnectionConfig) -> None:
        self._session = config.async_session_local

    # Run lifecycle (writes)

    async def reap_stale_runs(
        self, *, max_age: timedelta = timedelta(hours=1)
    ) -> int:
        statement = (
            update(ComputationRunLog)
            .where(
                ComputationRunLog.status == "RUNNING",
                ComputationRunLog.started_at < func.now() - max_age,
            )
            .values(
                status="FAILED",
                finished_at=func.now(),
                error_message="STALE_RUN_REAPED",
            )
            .returning(ComputationRunLog.run_id)
        )
        async with self._session.begin() as session:
            result = await session.execute(statement)
            return _returned_count(result)

    async def last_succeeded_fingerprint(self) -> str | None:
        statement = (
            select(ComputationRunLog.input_fingerprint)
            .where(ComputationRunLog.status == "SUCCEEDED")
            .order_by(
                ComputationRunLog.finished_at.desc(),
                ComputationRunLog.started_at.desc(),
            )
            .limit(1)
        )
        async with self._session.begin() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none()

    async def start_run(
        self,
        fingerprint: str | None,
        *,
        run_id: UUID | None = None,
        started_at: datetime | None = None,
    ) -> UUID:
        run_id = run_id or uuid4()
        started_at = started_at or now_utc()
        statement = insert(ComputationRunLog).values(
            run_id=run_id,
            started_at=started_at,
            status="RUNNING",
            input_fingerprint=fingerprint,
        )
        try:
            async with self._session.begin() as session:
                await session.execute(statement)
        except IntegrityError as error:
            if is_run_in_progress_integrity_error(error):
                raise MetricsRunInProgress from error
            raise
        return run_id

    async def publish_run(
        self,
        run_id: UUID,
        result: ComputationResult,
        *,
        computed_at: datetime,
        finished_at: datetime | None = None,
        chunk_size: int = 5000,
    ) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be at least 1")

        async with self._session.begin() as session:
            for model, result_attribute in _METRIC_TABLES:
                rows = getattr(result, result_attribute)
                for chunk in _chunks(rows, chunk_size):
                    values = [{**row, "run_id": run_id} for row in chunk]
                    await session.execute(insert(model), values)

            status_update = (
                update(ComputationRunLog)
                .where(
                    ComputationRunLog.run_id == run_id,
                    ComputationRunLog.status == "RUNNING",
                )
                .values(
                    status="SUCCEEDED",
                    finished_at=func.coalesce(finished_at, func.now()),
                    computed_at=computed_at,
                    rows_processed=result.rows_processed,
                )
            )
            update_result = await session.execute(status_update)
            if getattr(update_result, "rowcount", None) != 1:
                raise RuntimeError("computation run was not RUNNING")

    async def finish_run(
        self,
        run_id: UUID,
        status: str,
        *,
        rows_processed: int | None = None,
        error_message: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        if status != "FAILED":
            raise ValueError("status must be FAILED")

        statement = (
            update(ComputationRunLog)
            .where(
                ComputationRunLog.run_id == run_id,
                ComputationRunLog.status == "RUNNING",
            )
            .values(
                status="FAILED",
                finished_at=finished_at or func.now(),
                rows_processed=rows_processed,
                error_message=error_message[:1000] if error_message else None,
            )
        )
        async with self._session.begin() as session:
            await session.execute(statement)

    async def prune(self, keep: int = 10) -> int:
        if keep < 1:
            raise ValueError("keep must be at least 1")

        run_selection = (
            select(ComputationRunLog.run_id)
            .where(
                ComputationRunLog.status == "SUCCEEDED",
                ComputationRunLog.pruned_at.is_(None),
            )
            .order_by(
                ComputationRunLog.finished_at.desc(),
                ComputationRunLog.started_at.desc(),
            )
            .offset(keep)
        )
        async with self._session.begin() as session:
            result = await session.execute(run_selection)
            run_ids = list(result.scalars().all())
            if not run_ids:
                return 0

            for model, _ in _METRIC_TABLES:
                await session.execute(
                    delete(model).where(model.run_id.in_(run_ids))
                )
            await session.execute(
                update(ComputationRunLog)
                .where(
                    ComputationRunLog.run_id.in_(run_ids),
                    ComputationRunLog.status == "SUCCEEDED",
                    ComputationRunLog.pruned_at.is_(None),
                )
                .values(pruned_at=func.now())
            )
            return len(run_ids)

    # Published snapshot reads

    @staticmethod
    async def _latest_run_id_for_session(session: Any) -> UUID | None:
        statement = (
            select(ComputationRunLog.run_id)
            .where(
                ComputationRunLog.status == "SUCCEEDED",
                ComputationRunLog.pruned_at.is_(None),
            )
            .order_by(
                ComputationRunLog.finished_at.desc(),
                ComputationRunLog.started_at.desc(),
            )
            .limit(1)
        )
        result = await session.execute(statement)
        return result.scalar_one_or_none()

    async def latest_run_id(self) -> UUID | None:
        try:
            async with self._session.begin() as session:
                return await self._latest_run_id_for_session(session)
        except (SQLAlchemyError, OSError, TimeoutError) as error:
            raise MetricsStoreUnavailable(type(error).__name__) from error

    async def period_summary(
        self,
        facility_id: UUID | None,
        grain: str,
        *,
        run_id: UUID | None = None,
    ) -> list[dict]:
        statement = select(*_ROW_COLUMNS[MetricPeriodSummary]).where(
            MetricPeriodSummary.period_grain == grain
        )
        statement = self._scope_aggregate(
            statement, MetricPeriodSummary, facility_id
        ).order_by(
            MetricPeriodSummary.period_start.asc(),
            MetricPeriodSummary.facility_id.asc().nullslast(),
        )
        return await self._fetch_rows(statement, MetricPeriodSummary, run_id)

    async def comorbidity(
        self,
        facility_id: UUID | None,
        grain: str,
        *,
        run_id: UUID | None = None,
    ) -> list[dict]:
        statement = select(*_ROW_COLUMNS[MetricComorbidityBreakdown]).where(
            MetricComorbidityBreakdown.period_grain == grain
        )
        statement = self._scope_aggregate(
            statement, MetricComorbidityBreakdown, facility_id
        ).order_by(
            MetricComorbidityBreakdown.period_start.asc(),
            MetricComorbidityBreakdown.diagnosis_label.asc(),
            MetricComorbidityBreakdown.facility_id.asc().nullslast(),
        )
        return await self._fetch_rows(
            statement, MetricComorbidityBreakdown, run_id
        )

    async def out_of_control(
        self,
        facility_id: UUID | None,
        *,
        run_id: UUID | None = None,
    ) -> list[dict]:
        statement = select(*_ROW_COLUMNS[PatientCurrentState]).where(
            PatientCurrentState.is_out_of_control.is_(True)
        )
        statement = self._scope_patient_state(statement, facility_id).order_by(
            PatientCurrentState.is_bp_crisis.desc().nullslast(),
            PatientCurrentState.last_visit_date.desc().nullslast(),
            PatientCurrentState.patient_key.asc(),
        )
        return await self._fetch_rows(statement, PatientCurrentState, run_id)

    async def data_quality(
        self,
        facility_id: UUID | None,
        grain: str,
        *,
        run_id: UUID | None = None,
    ) -> list[dict]:
        statement = select(*_ROW_COLUMNS[MetricDataQualitySummary]).where(
            MetricDataQualitySummary.period_grain == grain
        )
        statement = self._scope_aggregate(
            statement, MetricDataQualitySummary, facility_id
        ).order_by(
            MetricDataQualitySummary.period_start.asc(),
            MetricDataQualitySummary.facility_id.asc().nullslast(),
        )
        return await self._fetch_rows(
            statement, MetricDataQualitySummary, run_id
        )

    async def last_computed_at(
        self, *, run_id: UUID | None = None
    ) -> datetime | None:
        try:
            async with self._session.begin() as session:
                effective_run_id = run_id or await self._latest_run_id_for_session(
                    session
                )
                if effective_run_id is None:
                    return None
                result = await session.execute(
                    select(ComputationRunLog.computed_at).where(
                        ComputationRunLog.run_id == effective_run_id
                    )
                )
                return result.scalar_one_or_none()
        except (SQLAlchemyError, OSError, TimeoutError) as error:
            raise MetricsStoreUnavailable(type(error).__name__) from error

    async def _fetch_rows(
        self, statement: Select, model: Any, run_id: UUID | None
    ) -> list[dict]:
        try:
            async with self._session.begin() as session:
                effective_run_id = run_id or await self._latest_run_id_for_session(
                    session
                )
                if effective_run_id is None:
                    return []
                result = await session.execute(
                    statement.where(model.run_id == effective_run_id)
                )
                return [dict(row) for row in result.mappings().all()]
        except (SQLAlchemyError, OSError, TimeoutError) as error:
            raise MetricsStoreUnavailable(type(error).__name__) from error

    @staticmethod
    def _scope_aggregate(statement: Select, model: Any, facility_id: UUID | None):
        if facility_id is None:
            return statement
        return statement.where(model.facility_id == facility_id)

    @staticmethod
    def _scope_patient_state(statement: Select, facility_id: UUID | None):
        if facility_id is None:
            return statement
        return statement.where(PatientCurrentState.facility_id == facility_id)


__all__ = ["MetricsRepository"]
