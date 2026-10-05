"""Visit volume and patient-repeat metrics."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import pandas as pd

from ..periods import to_local_naive


def _keys(frame: pd.DataFrame) -> pd.Series:
    if "patient_key" not in frame:
        return pd.Series(dtype="string", index=frame.index)
    keys = frame["patient_key"].astype("string")
    return keys.loc[keys.notna() & keys.ne("nan")]


def _as_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce", format="mixed")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(to_local_naive(pd.Timestamp(parsed)))


def compute_coverage(
    frame: pd.DataFrame,
    *,
    first_visit_dates: Mapping[str, Any] | None = None,
    period_start: datetime | pd.Timestamp | None = None,
    period_end: datetime | pd.Timestamp | None = None,
) -> dict[str, int | float | None]:
    """Compute counts for one half-open period slice."""

    keys = _keys(frame)
    unique_keys = set(keys.tolist())
    unique_count = len(unique_keys)
    first_dates = first_visit_dates or {}
    start = _as_timestamp(period_start)
    end = _as_timestamp(period_end)

    new_count = 0
    if start is not None:
        for key in unique_keys:
            first = _as_timestamp(first_dates.get(str(key)))
            if first is not None and (end is None or first < end) and first >= start:
                new_count += 1

    returning_count = 0
    if unique_count and "patient_key" in frame:
        counts = keys.value_counts()
        returning_count = int((counts >= 2).sum())

    return {
        "visit_count": len(frame),
        "unique_patient_count": unique_count,
        "new_patient_count": new_count,
        "returning_patient_count": returning_count,
        "repeat_visit_ratio": (
            returning_count / unique_count if unique_count else None
        ),
    }
