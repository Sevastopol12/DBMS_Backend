from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from .bucketing import assign_buckets, localize_local, to_local_naive
from .identity import add_patient_key
from .metrics.clinical_control import compute_clinical_control
from .metrics.coverage import compute_coverage
from .metrics.data_quality import compute_data_quality
from .metrics.disease_burden import (
    compute_comorbidity_breakdown,
    compute_disease_burden,
)
from .metrics.patient_state import build_patient_state
from .models import PeriodGrain


@dataclass(frozen=True)
class ComputationResult:
    period_summary_rows: list[dict]
    comorbidity_rows: list[dict]
    patient_state_rows: list[dict]
    data_quality_rows: list[dict]
    rows_processed: int


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _python_time(value: Any) -> datetime | None:
    if value is None or _is_missing(value):
        return None
    return localize_local(pd.Timestamp(value))


def _facility_values(*frames: pd.DataFrame) -> list[Any]:
    values: list[Any] = []
    seen: set[str] = set()
    for frame in frames:
        if "facility_id" not in frame:
            continue
        for value in frame["facility_id"].tolist():
            if _is_missing(value):
                continue
            marker = repr(value)
            if marker not in seen:
                values.append(value)
                seen.add(marker)
    return values


def _facility_slice(frame: pd.DataFrame, facility_id: Any) -> pd.DataFrame:
    if "facility_id" not in frame:
        return frame.iloc[0:0].copy()
    return frame.loc[frame["facility_id"].map(lambda value: value == facility_id)].copy()


def _period_groups(
    frame: pd.DataFrame,
    grain: PeriodGrain,
    *,
    date_col: str,
    run_at: datetime,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]]:
    bucketed = assign_buckets(frame, grain, date_col=date_col, run_at=run_at)
    if bucketed.empty:
        return []
    grouped: list[tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]] = []
    for (start, end), period in bucketed.dropna(
        subset=["_period_start", "_period_end"]
    ).groupby(["_period_start", "_period_end"], sort=True):
        grouped.append((pd.Timestamp(start), pd.Timestamp(end), period))
    return grouped


class ComputationPipeline:
    """Compute every metric table from accepted report rows and file reports."""

    def compute(
        self,
        report_df: pd.DataFrame,
        files_df: pd.DataFrame,
        run_at: datetime,
    ) -> ComputationResult:
        normalized_run_at = pd.Timestamp(run_at)
        if normalized_run_at.tzinfo is None:
            normalized_run_at = normalized_run_at.tz_localize("UTC")
        normalized_run_at = normalized_run_at.to_pydatetime()

        report = add_patient_key(report_df.copy())
        if "ngay_kham" in report:
            report["ngay_kham"] = to_local_naive(
                pd.to_datetime(report["ngay_kham"], errors="coerce", format="mixed")
            )
        files = files_df.copy()
        if "completed_at" in files:
            files["completed_at"] = to_local_naive(
                pd.to_datetime(files["completed_at"], errors="coerce", format="mixed")
            )

        first_visits: dict[str, pd.Timestamp] = {}
        if not report.empty and "ngay_kham" in report:
            first = report.dropna(subset=["ngay_kham"]).groupby("patient_key")[
                "ngay_kham"
            ].min()
            first_visits = first.to_dict()

        period_rows: list[dict] = []
        comorbidity_rows: list[dict] = []
        facilities = _facility_values(report)
        for facility_id in [*facilities, None]:
            scope = report if facility_id is None else _facility_slice(report, facility_id)
            for grain in PeriodGrain:
                for start, end, period in _period_groups(
                    scope, grain, date_col="ngay_kham", run_at=normalized_run_at
                ):
                    coverage = compute_coverage(
                        period,
                        first_visit_dates=first_visits,
                        period_start=start,
                        period_end=end,
                    )
                    disease = compute_disease_burden(period)
                    clinical = compute_clinical_control(period)
                    row = {
                        "facility_id": facility_id,
                        "period_grain": grain.value,
                        "period_start": _python_time(start),
                        "period_end": _python_time(end),
                        **coverage,
                        **disease,
                        **clinical,
                        "uploaded_date": normalized_run_at,
                    }
                    period_rows.append(row)
                    for breakdown in compute_comorbidity_breakdown(period):
                        comorbidity_rows.append(
                            {
                                "facility_id": facility_id,
                                "period_grain": grain.value,
                                "period_start": _python_time(start),
                                "uploaded_date": normalized_run_at,
                                **breakdown,
                            }
                        )

        state_rows = build_patient_state(report, run_at=normalized_run_at)
        quality_rows = self._compute_quality_rows(files, facilities, normalized_run_at)
        return ComputationResult(
            period_summary_rows=period_rows,
            comorbidity_rows=comorbidity_rows,
            patient_state_rows=state_rows,
            data_quality_rows=quality_rows,
            rows_processed=len(report_df),
        )

    @staticmethod
    def _compute_quality_rows(
        files: pd.DataFrame,
        report_facilities: list[Any],
        run_at: datetime,
    ) -> list[dict]:
        if "completed_at" not in files or files.empty:
            return []
        facilities = _facility_values(files)
        for facility in report_facilities:
            if repr(facility) not in {repr(value) for value in facilities}:
                facilities.append(facility)
        rows: list[dict] = []
        for facility_id in [*facilities, None]:
            scope = files if facility_id is None else _facility_slice(files, facility_id)
            for grain in PeriodGrain:
                for start, end, period in _period_groups(
                    scope, grain, date_col="completed_at", run_at=run_at
                ):
                    row = compute_data_quality(
                        period,
                        facility_id=facility_id,
                        period_grain=grain.value,
                        period_start=_python_time(start),
                        period_end=_python_time(end),
                    )
                    row["uploaded_date"] = run_at
                    rows.append(row)
        return rows


__all__ = ["ComputationPipeline", "ComputationResult"]
