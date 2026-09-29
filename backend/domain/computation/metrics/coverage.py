"""Visit volume and patient-repeat metrics."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import pandas as pd

from ..bucketing import to_local_naive


def _non_null_keys(frame: pd.DataFrame) -> pd.Series:
    if "patient_key" in frame:
        return frame["patient_key"].dropna().astype(str)
    return pd.Series(frame.index.astype(str), index=frame.index)


def _as_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    timestamp = pd.Timestamp(parsed)
    return to_local_naive(timestamp)


def compute_coverage(
    frame: pd.DataFrame,
    *,
    first_visit_dates: Mapping[str, Any] | None = None,
    period_start: datetime | pd.Timestamp | None = None,
    period_end: datetime | pd.Timestamp | None = None,
) -> dict[str, int | float | None]:
    """Compute visit/unique/new-returning counts for one period slice."""

    keys = _non_null_keys(frame)
    unique_keys = set(keys.tolist())
    visit_count = len(frame)
    unique_count = len(unique_keys)
    first_dates = first_visit_dates or {}
    start = _as_timestamp(period_start)
    end = _as_timestamp(period_end)
    new_count = 0

    if start is not None:
        for key in unique_keys:
            first = _as_timestamp(first_dates.get(key))
            if first is not None and (
                (end is not None and start <= first < end)
                or (end is None and first == start)
            ):
                new_count += 1
    else:
        new_count = unique_count

    return {
        "visit_count": visit_count,
        "unique_patient_count": unique_count,
        "new_patient_count": new_count,
        "returning_patient_count": unique_count - new_count,
        "repeat_visit_ratio": visit_count / unique_count if unique_count else None,
    }
