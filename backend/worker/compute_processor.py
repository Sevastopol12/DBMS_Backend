from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.errors import MetricsRunInProgress
from backend.database.service.metrics.repository import MetricsRepository
from backend.database.service.production.schema import SystemReport
from backend.database.service.staging.schema import FileInfo
from backend.domain.computation.pipeline import ComputationPipeline, ComputationResult
from backend.redis_cache.cache import MetricsCache
from backend.redis_cache.keys import (
    LAST_COMPUTED_AT_KEY,
    METRICS_CACHE_TTL_SECONDS,
    comorbidity_key,
    data_quality_key,
    out_of_control_key,
    period_summary_key,
    sort_comorbidity,
    sort_data_quality,
    sort_out_of_control,
    sort_period_summary,
)
from backend.timezone import now_utc

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1"


def compute_fingerprint(
    report_stats: Any,
    file_stats: Any,
    version: str,
) -> str:
    """Return a stable digest for the inputs and the deployed pipeline version."""

    payload = {
        "file_stats": file_stats,
        "pipeline_version": version,
        "report_stats": report_stats,
    }
    canonical = json.dumps(
        payload,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _stats_from_result(result: Any) -> tuple[Any, Any]:
    """Extract the two values returned by a count/max aggregate query."""

    row = result.one()
    if hasattr(row, "_mapping"):
        values = tuple(row._mapping.values())
    elif isinstance(row, dict):
        values = tuple(row.values())
    else:
        values = tuple(row)
    if len(values) != 2:  # pragma: no cover - protects against query drift
        raise RuntimeError("input stats query returned an unexpected shape")
    return values[0], values[1]


async def _fetch_input_stats(
    production: RDBAsyncConnectionConfig,
    staging: RDBAsyncConnectionConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch the small fingerprint inputs in separate, short-lived sessions."""

    async with production.async_session_local() as session:
        result = await session.execute(
            select(func.count(SystemReport.id), func.max(SystemReport.id))
        )
        report_count, report_max_id = _stats_from_result(result)

    async with staging.async_session_local() as session:
        result = await session.execute(
            select(func.count(FileInfo.id), func.max(FileInfo.completed_at))
        )
        file_count, file_max_completed_at = _stats_from_result(result)

    return (
        {"count": report_count, "max_id": report_max_id},
        {"count": file_count, "max_completed_at": file_max_completed_at},
    )


async def _fetch_report_df(session: AsyncSession) -> pd.DataFrame:
    """Fetch accepted report rows as flat mapping records."""

    result = await session.execute(select(*SystemReport.__table__.columns))
    return pd.DataFrame(result.mappings().all())


async def _fetch_files_df(session: AsyncSession) -> pd.DataFrame:
    """Fetch the file metadata used by data-quality metrics."""

    result = await session.execute(
        select(
            FileInfo.id,
            FileInfo.facility_id,
            FileInfo.quality_report,
            FileInfo.completed_at,
            FileInfo.accepted_row_count,
            FileInfo.rejected_row_count,
        )
    )
    return pd.DataFrame(result.mappings().all())


def _write_metrics_cache(
    cache: MetricsCache,
    result: ComputationResult,
    computed_at: datetime,
) -> None:
    """Write sorted, non-empty cache entries for every result scope."""

    period_summary: defaultdict[tuple[Any, str], list[dict]] = defaultdict(list)
    period_summary_all: defaultdict[str, list[dict]] = defaultdict(list)
    for row in result.period_summary_rows:
        period_summary[(row["facility_id"], str(row["period_grain"]))].append(row)
        period_summary_all[str(row["period_grain"])].append(row)
    for grain, rows in period_summary_all.items():
        if rows:
            cache.set(
                period_summary_key(None, grain),
                sort_period_summary(rows),
                ttl_seconds=METRICS_CACHE_TTL_SECONDS,
            )
    for (facility_id, grain), rows in period_summary.items():
        if facility_id is not None and rows:
            cache.set(
                period_summary_key(facility_id, grain),
                sort_period_summary(rows),
                ttl_seconds=METRICS_CACHE_TTL_SECONDS,
            )

    comorbidity: defaultdict[tuple[Any, str], list[dict]] = defaultdict(list)
    comorbidity_all: defaultdict[str, list[dict]] = defaultdict(list)
    for row in result.comorbidity_rows:
        comorbidity[(row["facility_id"], str(row["period_grain"]))].append(row)
        comorbidity_all[str(row["period_grain"])].append(row)
    for grain, rows in comorbidity_all.items():
        if rows:
            cache.set(
                comorbidity_key(None, grain),
                sort_comorbidity(rows),
                ttl_seconds=METRICS_CACHE_TTL_SECONDS,
            )
    for (facility_id, grain), rows in comorbidity.items():
        if facility_id is not None and rows:
            cache.set(
                comorbidity_key(facility_id, grain),
                sort_comorbidity(rows),
                ttl_seconds=METRICS_CACHE_TTL_SECONDS,
            )

    out_of_control: defaultdict[Any, list[dict]] = defaultdict(list)
    for row in result.patient_state_rows:
        if row.get("is_out_of_control") is not True:
            continue
        out_of_control[None].append(row)
        if row.get("facility_id") is not None:
            out_of_control[row["facility_id"]].append(row)
    for facility_id, rows in out_of_control.items():
        if rows:
            cache.set(
                out_of_control_key(facility_id),
                sort_out_of_control(rows),
                ttl_seconds=METRICS_CACHE_TTL_SECONDS,
            )

    data_quality: defaultdict[tuple[Any, str], list[dict]] = defaultdict(list)
    data_quality_all: defaultdict[str, list[dict]] = defaultdict(list)
    for row in result.data_quality_rows:
        data_quality[(row["facility_id"], str(row["period_grain"]))].append(row)
        data_quality_all[str(row["period_grain"])].append(row)
    for grain, rows in data_quality_all.items():
        if rows:
            cache.set(
                data_quality_key(None, grain),
                sort_data_quality(rows),
                ttl_seconds=METRICS_CACHE_TTL_SECONDS,
            )
    for (facility_id, grain), rows in data_quality.items():
        if facility_id is not None and rows:
            cache.set(
                data_quality_key(facility_id, grain),
                sort_data_quality(rows),
                ttl_seconds=METRICS_CACHE_TTL_SECONDS,
            )

    cache.set(
        LAST_COMPUTED_AT_KEY,
        computed_at.isoformat(),
        ttl_seconds=METRICS_CACHE_TTL_SECONDS,
    )


class ComputeProcessor:
    """Run computation with task-owned database connection configs."""

    def __init__(
        self,
        production: RDBAsyncConnectionConfig,
        staging: RDBAsyncConnectionConfig,
        *,
        repository: MetricsRepository | None = None,
        pipeline: ComputationPipeline | None = None,
        metrics_cache: MetricsCache | None = None,
    ) -> None:
        self._production = production
        self._staging = staging
        self._repository = repository or MetricsRepository(production)
        self._pipeline = pipeline or ComputationPipeline()
        self._metrics_cache = metrics_cache

    async def run(self, *, force: bool = False) -> None:
        """Compute and atomically publish one append-only metrics run."""

        started = time.monotonic()
        await self._repository.reap_stale_runs()
        report_stats, file_stats = await _fetch_input_stats(
            self._production, self._staging
        )
        fingerprint = compute_fingerprint(report_stats, file_stats, PIPELINE_VERSION)
        if (
            not force
            and fingerprint == await self._repository.last_succeeded_fingerprint()
        ):
            logger.info("metrics unchanged, skipping")
            return

        try:
            run_id = await self._repository.start_run(fingerprint)
        except MetricsRunInProgress:
            logger.info("metrics already running")
            return

        logger.info("compute run started run_id=%s", run_id)
        try:
            async with self._production.async_session_local() as session:
                report_df = await _fetch_report_df(session)

            async with self._staging.async_session_local() as session:
                files_df = await _fetch_files_df(session)

            run_at = now_utc()
            result = self._pipeline.compute(report_df, files_df, run_at)
            await self._repository.publish_run(
                run_id,
                result,
                computed_at=run_at,
            )
        except Exception as exc:
            # Exception messages may contain row values or other sensitive data.
            # The run log only needs the class name for operational diagnosis.
            error_message = type(exc).__name__
            logger.error(
                "compute run failed run_id=%s error=%s",
                run_id,
                type(exc).__name__,
            )
            try:
                await self._repository.finish_run(
                    run_id,
                    "FAILED",
                    error_message=error_message,
                )
            except Exception as finish_error:
                logger.warning(
                    "compute run failure update failed run_id=%s error=%s",
                    run_id,
                    type(finish_error).__name__,
                )
            raise

        if self._metrics_cache is not None:
            try:
                _write_metrics_cache(self._metrics_cache, result, run_at)
            except Exception as exc:
                logger.warning(
                    "metrics cache write failed run_id=%s error=%s",
                    run_id,
                    type(exc).__name__,
                )

        try:
            await self._repository.prune(keep=10)
        except Exception as exc:
            logger.warning(
                "metrics run prune failed run_id=%s error=%s",
                run_id,
                type(exc).__name__,
            )

        logger.info(
            "compute run succeeded run_id=%s rows_processed=%s duration_seconds=%.3f",
            run_id,
            result.rows_processed,
            time.monotonic() - started,
        )


__all__ = ["PIPELINE_VERSION", "ComputeProcessor", "compute_fingerprint"]
