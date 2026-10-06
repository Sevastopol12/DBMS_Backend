from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import date, datetime
from numbers import Real
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.connection import RDBAsyncConnectionConfig
from backend.database.errors import MetricsRunInProgress
from backend.database.service.metrics.repository import MetricsRepository
from backend.database.service.production.schema import Demographic, Measurement
from backend.database.service.staging.schema import FileInfo
from backend.domain.computation.pipeline import ComputationPipeline, ComputationResult
from backend.redis_cache.cache import MetricsCache
from backend.redis_cache.keys import (
    LAST_COMPUTED_AT_KEY,
    METRICS_CACHE_PREFIXES,
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
from backend.timezone import now_utc, start_of_day_vietnam

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "3"
_METRIC_GRAINS = ("3D", "2W", "3M", "6M", "TODAY", "ALL")
_PERIOD_ROW_KEYS = (
    "facility_id",
    "period_grain",
    "period_start",
    "period_end",
    "visit_count",
    "unique_patient_count",
    "new_patient_count",
    "returning_patient_count",
    "repeat_visit_ratio",
    "pct_tha",
    "pct_dtd",
    "pct_comorbid",
    "bp_control_rate",
    "bp_stage_normal_count",
    "bp_stage_elevated_count",
    "bp_stage_1_count",
    "bp_stage_2_count",
    "bp_stage_severe_count",
    "glycemic_control_rate",
    "avg_glucose",
    "median_glucose",
    "avg_hba1c",
    "median_hba1c",
    "computed_at",
)
_COMORBIDITY_ROW_KEYS = (
    "facility_id",
    "period_grain",
    "period_start",
    "diagnosis_label",
    "patient_count",
    "computed_at",
)
_PATIENT_STATE_ROW_KEYS = (
    "patient_key",
    "facility_id",
    "ho_ten",
    "sdt",
    "dia_chi",
    "last_visit_date",
    "last_systolic",
    "last_diastolic",
    "last_glucose",
    "last_hba1c",
    "is_bp_controlled",
    "is_bp_severe",
    "is_hba1c_controlled",
    "is_out_of_control",
    "has_contact",
    "first_visit_date",
    "visit_count",
    "computed_at",
)
_DATA_QUALITY_ROW_KEYS = (
    "facility_id",
    "period_grain",
    "period_start",
    "period_end",
    "files_processed",
    "avg_mapping_coverage_ratio",
    "total_rows_seen",
    "accepted_rows",
    "rejected_rows",
    "ignored_duplicate_row_count",
    "top_issue_codes",
    "computed_at",
)
_REPORT_COLUMNS = (
    Demographic.facility_id,
    Demographic.cccd,
    Demographic.ngay_kham,
    Demographic.ho_ten,
    Demographic.nam_sinh,
    Demographic.sdt,
    Demographic.gioi_tinh,
    Demographic.dia_chi,
    Demographic.ma_bhyt,
    Demographic.ghi_chu,
    Demographic.dieu_tri,
    Measurement.icd_tha,
    Measurement.icd_dtd,
    Measurement.chan_doan_di_kem,
    Measurement.huyet_ap_tam_truong,
    Measurement.huyet_ap_tam_thu,
    Measurement.chi_so_duong_huyet,
    Measurement.chi_so_hba1c,
)


@dataclass(frozen=True)
class ComputeOutcome:
    status: str
    computation_run_id: UUID | None = None
    rows_processed: int | None = None


def _ensure_finite_metrics(value: Any) -> None:
    """Reject non-finite numeric values before a result reaches persistence."""

    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, Real):
        if not math.isfinite(value):
            raise ValueError("non-finite metric value")
        return
    if isinstance(value, dict):
        for nested in value.values():
            _ensure_finite_metrics(nested)
        return
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            _ensure_finite_metrics(nested)


def compute_fingerprint(
    report_stats: Any,
    file_stats: Any,
    version: str,
    cutoff: date,
) -> str:
    """Return a stable digest for the inputs and the deployed pipeline version."""

    payload = {
        "file_stats": file_stats,
        "pipeline_version": version,
        "report_stats": report_stats,
        "cutoff": cutoff,
    }
    canonical = json.dumps(
        payload,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _stats_from_result(result: Any) -> tuple[Any, ...]:
    """Extract the values returned by a count/max aggregate query."""

    row = result.one()
    if hasattr(row, "_mapping"):
        values = tuple(row._mapping.values())
    elif isinstance(row, dict):
        values = tuple(row.values())
    else:
        values = tuple(row)
    if not values:  # pragma: no cover - protects against query drift
        raise RuntimeError("input stats query returned an unexpected shape")
    return values


async def _fetch_input_stats(
    production: RDBAsyncConnectionConfig,
    staging: RDBAsyncConnectionConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch the small fingerprint inputs in separate, short-lived sessions.

    Fingerprint (D-10): ``(count, max(source_file_uploaded_at),
    max(uploaded_at))`` over both accepted tables plus file stats, so an
    in-place record replacement changes the digest even though the row
    count is unchanged.
    """

    async with production.async_session_local() as session:
        result = await session.execute(
            select(
                func.count(Demographic.id),
                func.max(Demographic.source_file_uploaded_at),
                func.max(Demographic.uploaded_at),
            )
        )
        demo_count, demo_max_source, demo_max_uploaded = _stats_from_result(result)
        result = await session.execute(
            select(
                func.count(Measurement.id),
                func.max(Measurement.source_file_uploaded_at),
                func.max(Measurement.uploaded_at),
            )
        )
        meas_count, meas_max_source, meas_max_uploaded = _stats_from_result(result)

    async with staging.async_session_local() as session:
        result = await session.execute(
            select(func.count(FileInfo.id), func.max(FileInfo.completed_at))
        )
        file_count, file_max_completed_at = _stats_from_result(result)

    return (
        {
            "demographic": {
                "count": demo_count,
                "max_source_file_uploaded_at": demo_max_source,
                "max_uploaded_at": demo_max_uploaded,
            },
            "measurement": {
                "count": meas_count,
                "max_source_file_uploaded_at": meas_max_source,
                "max_uploaded_at": meas_max_uploaded,
            },
        },
        {"count": file_count, "max_completed_at": file_max_completed_at},
    )


async def _fetch_report_df(session: AsyncSession) -> pd.DataFrame:
    """Fetch accepted visits via the §4.8 Demographic⨝Measurement join."""

    statement = (
        select(*_REPORT_COLUMNS)
        .select_from(Demographic)
        .join(
            Measurement,
            (Measurement.facility_id == Demographic.facility_id)
            & (Measurement.cccd == Demographic.cccd)
            & (Measurement.ngay_kham == Demographic.ngay_kham),
        )
    )
    result = await session.execute(statement)
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


def _canonical_row(row: dict, family: str, computed_at: datetime) -> dict:
    """Adapt legacy pipeline names to the final persistence/cache contract."""

    value = dict(row)
    aliases = {
        "uploaded_date": "computed_at",
        "is_bp_crisis": "is_bp_severe",
        "bp_stage_crisis_count": "bp_stage_severe_count",
        "avg_coverage_ratio": "avg_mapping_coverage_ratio",
    }
    for old, new in aliases.items():
        if old in value and new not in value:
            value[new] = value[old]
        value.pop(old, None)
    if family == "period":
        value.setdefault("bp_stage_elevated_count", 0)
    value["computed_at"] = computed_at
    return value


def _canonical_result(
    result: ComputationResult, computed_at: datetime
) -> ComputationResult:
    return ComputationResult(
        period_summary_rows=[
            {
                key: _canonical_row(row, "period", computed_at).get(key)
                for key in _PERIOD_ROW_KEYS
            }
            for row in result.period_summary_rows
        ],
        comorbidity_rows=[
            {
                key: _canonical_row(row, "comorbidity", computed_at).get(key)
                for key in _COMORBIDITY_ROW_KEYS
            }
            for row in result.comorbidity_rows
        ],
        patient_state_rows=[
            {
                key: _canonical_row(row, "patient", computed_at).get(key)
                for key in _PATIENT_STATE_ROW_KEYS
            }
            for row in result.patient_state_rows
        ],
        data_quality_rows=[
            {
                key: _canonical_row(row, "quality", computed_at).get(key)
                for key in _DATA_QUALITY_ROW_KEYS
            }
            for row in result.data_quality_rows
        ],
        rows_processed=result.rows_processed,
    )


def _write_cache_value(cache: MetricsCache, key: str, value: object) -> None:
    try:
        cache.set(key, value, ttl_seconds=METRICS_CACHE_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - post-run cleanup is best-effort
        logger.warning(
            "metrics cache write failed key=%s error=%s",
            key,
            type(exc).__name__,
        )


def _write_metrics_cache(
    cache: MetricsCache,
    result: ComputationResult,
    computed_at: datetime,
) -> None:
    """Write the complete cache snapshot and best-effort prune stale keys."""

    canonical = _canonical_result(result, computed_at)
    families = {
        "period": canonical.period_summary_rows,
        "comorbidity": canonical.comorbidity_rows,
        "patient": canonical.patient_state_rows,
        "quality": canonical.data_quality_rows,
    }
    facility_tokens = sorted(
        {
            str(row["facility_id"])
            for rows in families.values()
            for row in rows
            if row.get("facility_id") is not None
        }
    )
    expected: dict[str, list[dict]] = {}

    def scoped(rows: list[dict], facility: str) -> list[dict]:
        return [row for row in rows if str(row.get("facility_id")) == facility]

    for facility in facility_tokens:
        for grain in _METRIC_GRAINS:
            rows = scoped(families["period"], facility)
            rows = [row for row in rows if str(row.get("period_grain")) == grain]
            expected[period_summary_key(facility, grain)] = sort_period_summary(rows)

            rows = scoped(families["comorbidity"], facility)
            rows = [row for row in rows if str(row.get("period_grain")) == grain]
            expected[comorbidity_key(facility, grain)] = sort_comorbidity(rows)

            rows = scoped(families["quality"], facility)
            rows = [row for row in rows if str(row.get("period_grain")) == grain]
            expected[data_quality_key(facility, grain)] = sort_data_quality(rows)

        rows = [
            row
            for row in scoped(families["patient"], facility)
            if row.get("is_out_of_control") is True
        ]
        expected[out_of_control_key(facility)] = sort_out_of_control(rows)

    for key, value in expected.items():
        _write_cache_value(cache, key, value)
    _write_cache_value(
        cache,
        LAST_COMPUTED_AT_KEY,
        computed_at.isoformat(),
    )

    scan_keys = getattr(cache, "scan_keys", None)
    delete_many = getattr(cache, "delete_many", None)
    if not callable(scan_keys) or not callable(delete_many):
        return
    written = set(expected)
    for prefix in METRICS_CACHE_PREFIXES:
        try:
            stale = [key for key in scan_keys(prefix) if key not in written]
            if stale:
                delete_many(stale)
        except Exception as exc:  # noqa: BLE001 - post-run cleanup is best-effort
            logger.warning(
                "metrics cache prune failed prefix=%s error=%s",
                prefix,
                type(exc).__name__,
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

    async def run(self, *, force: bool = False) -> ComputeOutcome:
        """Compute and atomically publish one append-only metrics run."""

        run_at = now_utc()
        cutoff = start_of_day_vietnam(run_at).date()
        started = time.monotonic()
        await self._repository.reap_stale_runs()
        report_stats, file_stats = await _fetch_input_stats(
            self._production, self._staging
        )
        fingerprint = compute_fingerprint(
            report_stats, file_stats, PIPELINE_VERSION, cutoff
        )
        if (
            not force
            and fingerprint == await self._repository.last_succeeded_fingerprint()
        ):
            logger.info("metrics unchanged, skipping")
            return ComputeOutcome("SKIPPED_UNCHANGED")

        try:
            run_id = await self._repository.start_run(fingerprint)
        except MetricsRunInProgress:
            logger.info("metrics already running")
            return ComputeOutcome("SKIPPED_IN_PROGRESS")

        logger.info("compute run started run_id=%s", run_id)
        try:
            async with self._production.async_session_local() as session:
                report_df = await _fetch_report_df(session)

            async with self._staging.async_session_local() as session:
                files_df = await _fetch_files_df(session)

            result = _canonical_result(
                self._pipeline.compute(report_df, files_df, run_at), run_at
            )
            _ensure_finite_metrics(
                (
                    result.period_summary_rows,
                    result.comorbidity_rows,
                    result.patient_state_rows,
                    result.data_quality_rows,
                )
            )
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
            except Exception as finish_error:  # noqa: BLE001 - must not mask original failure
                logger.warning(
                    "compute run failure update failed run_id=%s error=%s",
                    run_id,
                    type(finish_error).__name__,
                )
            raise

        if self._metrics_cache is not None:
            try:
                _write_metrics_cache(self._metrics_cache, result, run_at)
            except Exception as exc:  # noqa: BLE001 - post-run cleanup is best-effort
                logger.warning(
                    "metrics cache write failed run_id=%s error=%s",
                    run_id,
                    type(exc).__name__,
                )

        try:
            await self._repository.prune(keep=10)
        except Exception as exc:  # noqa: BLE001 - post-run cleanup is best-effort
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
        return ComputeOutcome(
            "SUCCEEDED", computation_run_id=run_id, rows_processed=result.rows_processed
        )


__all__ = [
    "PIPELINE_VERSION",
    "_REPORT_COLUMNS",
    "ComputeOutcome",
    "ComputeProcessor",
    "compute_fingerprint",
]
