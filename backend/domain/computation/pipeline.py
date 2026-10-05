from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from .identity import resolve_patient_key
from .metrics.clinical_control import compute_clinical_control, parse_measurements
from .metrics.coverage import compute_coverage
from .metrics.data_quality import compute_data_quality, quality_eligible_mask
from .metrics.disease_burden import (
    compute_comorbidity_breakdown,
    compute_disease_burden,
)
from .metrics.patient_state import build_patient_state
from .models import PeriodGrain
from .periods import (
    PeriodWindow,
    all_window,
    build_period_windows,
    localize_local,
    to_local_naive,
)

logger = logging.getLogger(__name__)


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


def _same_facility(value: Any, facility_id: Any) -> bool:
    if _is_missing(value):
        return False
    try:
        return bool(value == facility_id)
    except (TypeError, ValueError):
        return repr(value) == repr(facility_id)


def _facility_slice(frame: pd.DataFrame, facility_id: Any) -> pd.DataFrame:
    if "facility_id" not in frame:
        return frame.iloc[0:0].copy()
    return frame.loc[frame["facility_id"].map(lambda value: _same_facility(value, facility_id))]


def _scope(frame: pd.DataFrame, facility_id: Any) -> pd.DataFrame:
    return frame if facility_id is None else _facility_slice(frame, facility_id)


def _normalize_run_at(run_at: datetime) -> datetime:
    timestamp = to_local_naive(pd.Timestamp(run_at))
    return localize_local(timestamp)


def _date_mask(frame: pd.DataFrame, start: Any, end: Any) -> pd.Series:
    if "ngay_kham" not in frame:
        return pd.Series(False, index=frame.index, dtype=bool)
    dates = frame["ngay_kham"]
    start_naive = to_local_naive(pd.Timestamp(start))
    end_naive = to_local_naive(pd.Timestamp(end))
    return dates.notna() & dates.ge(start_naive) & dates.lt(end_naive)


def _completed_mask(frame: pd.DataFrame, start: Any, end: Any) -> pd.Series:
    if "completed_at" not in frame:
        return pd.Series(False, index=frame.index, dtype=bool)
    dates = frame["completed_at"]
    start_naive = to_local_naive(pd.Timestamp(start))
    end_naive = to_local_naive(pd.Timestamp(end))
    return dates.notna() & dates.ge(start_naive) & dates.lt(end_naive)


def _identity_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        result = frame.copy()
        result["patient_key"] = pd.Series(dtype="string", index=result.index)
        return result
    result_rows: list[int] = []
    keys: list[str] = []
    dropped = 0
    for index, row in frame.iterrows():
        try:
            key = resolve_patient_key(
                row.get("cccd"),
                row.get("ho_ten"),
                row.get("nam_sinh"),
                row.get("dia_chi"),
            )
        except ValueError:
            dropped += 1
            continue
        result_rows.append(index)
        keys.append(key)
    if dropped:
        logger.warning("dropped %d report rows with invalid identity", dropped)
    result = frame.loc[result_rows].copy()
    result["patient_key"] = keys
    return result


def _normalize_report(report_df: pd.DataFrame) -> pd.DataFrame:
    report = _identity_frame(report_df.copy())
    if "ngay_kham" in report:
        report["ngay_kham"] = to_local_naive(
            pd.to_datetime(report["ngay_kham"], errors="coerce", format="mixed")
        )
    else:
        report["ngay_kham"] = pd.NaT
    return parse_measurements(report)


def _normalize_files(files_df: pd.DataFrame) -> pd.DataFrame:
    files = files_df.copy()
    if "completed_at" in files:
        files["completed_at"] = to_local_naive(
            pd.to_datetime(files["completed_at"], errors="coerce", format="mixed")
        )
    else:
        files["completed_at"] = pd.NaT
    return files


def _summary_row(
    facility_id: Any,
    grain: PeriodGrain,
    window: PeriodWindow,
    period: pd.DataFrame,
    first_visits: dict[str, Any],
    computed_at: datetime,
) -> dict[str, Any]:
    return {
        "facility_id": facility_id,
        "period_grain": grain.value,
        "period_start": window.start,
        "period_end": window.end,
        **compute_coverage(
            period,
            first_visit_dates=first_visits,
            period_start=window.start,
            period_end=window.end,
        ),
        **compute_disease_burden(period),
        **compute_clinical_control(period),
        "computed_at": computed_at,
    }


class ComputationPipeline:
    """Compute all metric tables from accepted rows and file reports."""

    def compute(
        self,
        report_df: pd.DataFrame,
        files_df: pd.DataFrame,
        run_at: datetime,
    ) -> ComputationResult:
        normalized_run_at = _normalize_run_at(run_at)
        cutoff = pd.Timestamp(to_local_naive(pd.Timestamp(normalized_run_at)))
        source_report_facilities = _facility_values(report_df)
        report = _normalize_report(report_df)
        files = _normalize_files(files_df)

        if "ngay_kham" in report:
            report = report.loc[report["ngay_kham"].notna() & report["ngay_kham"].lt(cutoff)].copy()

        first_visits: dict[str, Any] = {}
        if not report.empty:
            first_visits = report.groupby("patient_key")["ngay_kham"].min().to_dict()

        period_rows: list[dict] = []
        comorbidity_rows: list[dict] = []
        report_facilities = source_report_facilities
        for facility_id in [*report_facilities, None] if not report_df.empty else []:
            scope = _scope(report, facility_id)
            for window in build_period_windows(normalized_run_at):
                period = scope.loc[_date_mask(scope, window.start, window.end)]
                period_rows.append(
                    _summary_row(
                        facility_id,
                        window.grain,
                        window,
                        period,
                        first_visits,
                        normalized_run_at,
                    )
                )
                if not period.empty:
                    for breakdown in compute_comorbidity_breakdown(period):
                        comorbidity_rows.append(
                            {
                                "facility_id": facility_id,
                                "period_grain": window.grain.value,
                                "period_start": window.start,
                                **breakdown,
                                "computed_at": normalized_run_at,
                            }
                        )

            historical = scope.loc[scope["ngay_kham"].lt(cutoff)]
            if not historical.empty:
                window = all_window(historical["ngay_kham"].min(), normalized_run_at)
                period = historical.loc[_date_mask(historical, window.start, window.end)]
                if not period.empty:
                    period_rows.append(
                        _summary_row(
                            facility_id,
                            PeriodGrain.ALL,
                            window,
                            period,
                            first_visits,
                            normalized_run_at,
                        )
                    )
                    for breakdown in compute_comorbidity_breakdown(period):
                        comorbidity_rows.append(
                            {
                                "facility_id": facility_id,
                                "period_grain": PeriodGrain.ALL.value,
                                "period_start": window.start,
                                **breakdown,
                                "computed_at": normalized_run_at,
                            }
                        )

        state_rows = build_patient_state(report, run_at=normalized_run_at)
        quality_rows = self._compute_quality_rows(
            files, report_facilities, normalized_run_at
        )
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
        file_facilities = _facility_values(files)
        facilities = [*report_facilities]
        for facility in file_facilities:
            if repr(facility) not in {repr(value) for value in facilities}:
                facilities.append(facility)
        if not facilities:
            return []

        cutoff = pd.Timestamp(to_local_naive(pd.Timestamp(run_at)))
        rows: list[dict] = []
        for facility_id in [*facilities, None]:
            scope = _scope(files, facility_id)
            eligible_quality = quality_eligible_mask(scope)
            if not eligible_quality.index.equals(scope.index):
                eligible_quality = eligible_quality.reindex(scope.index, fill_value=False)
            for window in build_period_windows(run_at):
                period = scope.loc[_completed_mask(scope, window.start, window.end)]
                row = compute_data_quality(
                    period,
                    facility_id=facility_id,
                    period_grain=window.grain.value,
                    period_start=window.start,
                    period_end=window.end,
                )
                row["computed_at"] = run_at
                rows.append(row)

            eligible_dates = scope.loc[
                eligible_quality
                & scope["completed_at"].notna()
                & scope["completed_at"].lt(cutoff),
                "completed_at",
            ]
            if not eligible_dates.empty:
                start = localize_local(eligible_dates.min().normalize())
                window = PeriodWindow(PeriodGrain.ALL, start, run_at)
                period = scope.loc[
                    eligible_quality
                    & scope["completed_at"].notna()
                    & scope["completed_at"].lt(cutoff)
                ]
                row = compute_data_quality(
                    period,
                    facility_id=facility_id,
                    period_grain=PeriodGrain.ALL.value,
                    period_start=window.start,
                    period_end=window.end,
                )
                row["computed_at"] = run_at
                rows.append(row)
        return rows


__all__ = ["ComputationPipeline", "ComputationResult"]
