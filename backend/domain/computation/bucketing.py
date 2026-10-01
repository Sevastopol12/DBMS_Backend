from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from backend.timezone import VIETNAM_TZ_NAME

from .models import PeriodGrain

ORIGIN = pd.Timestamp("2020-01-01")
BUCKET_TZ = VIETNAM_TZ_NAME


@dataclass(frozen=True)
class BucketSpec:
    grain: PeriodGrain
    freq: str | None
    origin: pd.Timestamp
    label: str


BUCKET_SPECS: dict[PeriodGrain, BucketSpec] = {
    PeriodGrain.DAY: BucketSpec(PeriodGrain.DAY, "D", ORIGIN, "day"),
    PeriodGrain.THREE_DAYS: BucketSpec(
        PeriodGrain.THREE_DAYS, "3D", ORIGIN, "3-day period"
    ),
    PeriodGrain.WEEK: BucketSpec(PeriodGrain.WEEK, "W-MON", ORIGIN, "week"),
    PeriodGrain.TWO_WEEKS: BucketSpec(
        PeriodGrain.TWO_WEEKS, "2W-MON", ORIGIN, "2-week period"
    ),
    PeriodGrain.MONTH: BucketSpec(PeriodGrain.MONTH, "MS", ORIGIN, "month"),
    PeriodGrain.ALL: BucketSpec(PeriodGrain.ALL, None, ORIGIN, "all time"),
}


def get_bucket_spec(grain: PeriodGrain | str) -> BucketSpec:
    """Return the frozen pandas configuration for ``grain``."""

    normalized = grain if isinstance(grain, PeriodGrain) else PeriodGrain(grain)
    return BUCKET_SPECS[normalized]


def to_local_naive(value: Any) -> Any:
    """Convert aware timestamps to naive local wall time in ``BUCKET_TZ``."""

    if isinstance(value, pd.Series):
        parsed = pd.to_datetime(value, errors="coerce", format="mixed")
        if isinstance(parsed.dtype, pd.DatetimeTZDtype):
            return parsed.dt.tz_convert(BUCKET_TZ).dt.tz_localize(None)
        return parsed

    parsed = pd.Timestamp(value)
    if parsed.tzinfo is not None:
        return parsed.tz_convert(BUCKET_TZ).tz_localize(None)
    return parsed


def localize_local(value: Any) -> Any:
    """Localize naive local wall time to ``BUCKET_TZ``."""

    if isinstance(value, pd.Series):
        return value.dt.tz_localize(BUCKET_TZ)
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return pd.Timestamp(value).tz_localize(BUCKET_TZ).to_pydatetime()


def _parsed_datetimes(values: Any) -> pd.Series:
    return to_local_naive(pd.Series(pd.to_datetime(values, errors="coerce", format="mixed")))


def _timestamp(value: datetime | pd.Timestamp) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return to_local_naive(parsed)


def assign_buckets(
    frame: pd.DataFrame,
    grain: PeriodGrain | str,
    *,
    date_col: str = "ngay_kham",
    run_at: datetime | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Copy ``frame`` and add ``_period_start``/``_period_end`` columns.

    Fixed-origin ``resample`` is intentionally used for every non-``ALL``
    grain. ``ALL`` is a single explicit interval because it has no pandas
    frequency.
    """

    spec = get_bucket_spec(grain)
    result = frame.copy()
    if date_col not in result.columns:
        result["_period_start"] = pd.NaT
        result["_period_end"] = pd.NaT
        return result

    dates = _parsed_datetimes(result[date_col])
    result["_period_start"] = pd.NaT
    result["_period_end"] = pd.NaT
    valid = dates.notna()
    if not valid.any():
        return result

    if spec.freq is None:
        start = dates[valid].min()
        end = _timestamp(run_at) if run_at is not None else dates[valid].max()
        result.loc[valid, "_period_start"] = start
        result.loc[valid, "_period_end"] = end
        return result

    # A positional series avoids relying on a caller-provided, possibly
    # duplicated DataFrame index when translating resample bins back to rows.
    positions = pd.Series(
        list(range(len(result))), index=dates[valid].to_numpy(), dtype="object"
    )
    # ``origin`` is ignored by pandas for anchored, non-tick offsets such as
    # ``2W-MON``.  Without an explicit tick frequency, the first observed
    # date therefore changes the phase of two-week buckets when older data is
    # backfilled.  Anchor that grain to the Monday of the configured origin
    # week and use its equivalent 14-day tick instead.
    resample_freq = spec.freq
    resample_origin = spec.origin
    if spec.freq == "2W-MON":
        # Pandas treats day-based frequencies as non-tick offsets too; use
        # the equivalent hour count so ``origin`` is honored.
        resample_freq = "336h"
        resample_origin = spec.origin - pd.Timedelta(days=spec.origin.weekday())

    grouped = positions.resample(
        resample_freq,
        origin=resample_origin,
        label="left",
        closed="left",
    ).agg(list)
    starts: dict[int, pd.Timestamp] = {}
    ends: dict[int, pd.Timestamp] = {}
    offset = pd.tseries.frequencies.to_offset(spec.freq)
    for start, row_positions in grouped.items():
        if not row_positions:
            continue
        start = pd.Timestamp(start)
        end = start + offset
        for position in row_positions:
            starts[int(position)] = start
            ends[int(position)] = end

    result["_period_start"] = [starts.get(i, pd.NaT) for i in range(len(result))]
    result["_period_end"] = [ends.get(i, pd.NaT) for i in range(len(result))]
    return result


def bucket_frame(
    frame: pd.DataFrame,
    grain: PeriodGrain | str,
    *,
    date_col: str = "ngay_kham",
    run_at: datetime | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Backward-friendly alias for :func:`assign_buckets`."""

    return assign_buckets(frame, grain, date_col=date_col, run_at=run_at)


__all__ = [
    "BUCKET_SPECS",
    "BUCKET_TZ",
    "ORIGIN",
    "BucketSpec",
    "assign_buckets",
    "bucket_frame",
    "get_bucket_spec",
    "localize_local",
    "to_local_naive",
]
