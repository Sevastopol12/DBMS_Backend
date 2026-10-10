"""Explicit local-time windows for the computation run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from backend.timezone import VIETNAM_TZ, VIETNAM_TZ_NAME

from .models import PeriodGrain

BUCKET_TZ = VIETNAM_TZ_NAME


@dataclass(frozen=True)
class PeriodWindow:
    grain: PeriodGrain
    start: datetime
    end: datetime


def _local_aware(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(VIETNAM_TZ)
    return timestamp.tz_convert(VIETNAM_TZ)


def to_local_naive(value: Any) -> Any:
    """Convert a timestamp or timestamp series to Vietnam local wall time."""

    if isinstance(value, pd.Series):
        parsed = pd.to_datetime(value, errors="coerce", format="mixed")
        if isinstance(parsed.dtype, pd.DatetimeTZDtype):
            return parsed.dt.tz_convert(VIETNAM_TZ).dt.tz_localize(None)
        if parsed.dtype == object:

            def _one(item: Any) -> Any:
                if item is None or pd.isna(item):
                    return pd.NaT
                timestamp = pd.Timestamp(item)
                if timestamp.tzinfo is not None:
                    return timestamp.tz_convert(VIETNAM_TZ).tz_localize(None)
                return timestamp

            return parsed.map(_one)
        return parsed
    if value is None:
        return None
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is not None:
        return parsed.tz_convert(VIETNAM_TZ).tz_localize(None)
    return parsed


def localize_local(value: Any) -> Any:
    """Localize naive local wall time to Vietnam time."""

    if isinstance(value, pd.Series):
        if isinstance(value.dtype, pd.DatetimeTZDtype):
            return value.dt.tz_convert(VIETNAM_TZ)
        return value.dt.tz_localize(VIETNAM_TZ)
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(VIETNAM_TZ)
    else:
        timestamp = timestamp.tz_localize(VIETNAM_TZ)
    return timestamp.to_pydatetime()


def _midnight(value: pd.Timestamp) -> pd.Timestamp:
    local = _local_aware(value)
    return local.normalize()


def _as_datetime(value: pd.Timestamp) -> datetime:
    return value.to_pydatetime()


def build_period_windows(run_at: datetime) -> tuple[PeriodWindow, ...]:
    """Build the five fixed windows ending at the start of the run day."""

    cutoff = _local_aware(run_at)
    today = cutoff.normalize()
    return (
        PeriodWindow(
            PeriodGrain.THREE_DAYS,
            _as_datetime(today - pd.Timedelta(days=3)),
            _as_datetime(today),
        ),
        PeriodWindow(
            PeriodGrain.TWO_WEEKS,
            _as_datetime(today - pd.Timedelta(days=14)),
            _as_datetime(today),
        ),
        PeriodWindow(
            PeriodGrain.THREE_MONTHS,
            _as_datetime(today - pd.DateOffset(months=3)),
            _as_datetime(today),
        ),
        PeriodWindow(
            PeriodGrain.SIX_MONTHS,
            _as_datetime(today - pd.DateOffset(months=6)),
            _as_datetime(today),
        ),
        PeriodWindow(
            PeriodGrain.TODAY,
            _as_datetime(today),
            _as_datetime(cutoff),
        ),
    )


def all_window(earliest: Any, run_at: datetime) -> PeriodWindow:
    """Return the historical window, excluding the run day."""

    cutoff = _local_aware(run_at)
    return PeriodWindow(
        PeriodGrain.ALL,
        _as_datetime(_midnight(pd.Timestamp(earliest))),
        _as_datetime(cutoff.normalize()),
    )


__all__ = [
    "BUCKET_TZ",
    "PeriodWindow",
    "all_window",
    "build_period_windows",
    "localize_local",
    "to_local_naive",
]
