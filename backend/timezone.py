from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

VIETNAM_TZ_NAME = "Asia/Ho_Chi_Minh"
VIETNAM_TZ = ZoneInfo(VIETNAM_TZ_NAME)
UTC = UTC


def now_vietnam() -> datetime:
    """Return the current aware Vietnam-local datetime."""

    return datetime.now(VIETNAM_TZ)


def today_vietnam() -> date:
    """Return today's date according to the Vietnam-local calendar."""

    return now_vietnam().date()


def now_utc() -> datetime:
    """Return the current aware UTC datetime for an absolute instant."""

    return datetime.now(UTC)


def ensure_vietnam_aware(value: datetime) -> datetime:
    """Attach Vietnam timezone to a timezone-less local business datetime.

    Aware values are preserved as instants, including their original offset.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=VIETNAM_TZ)
    return value


def start_of_day_vietnam(value: datetime) -> datetime:
    """Return the start of ``value``'s Vietnam-local calendar day.

    Naive values are interpreted as Vietnam local time.  Aware values are
    converted to Vietnam time before the local date is truncated.
    """

    local = ensure_vietnam_aware(value).astimezone(VIETNAM_TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


__all__ = [
    "UTC",
    "VIETNAM_TZ",
    "VIETNAM_TZ_NAME",
    "ensure_vietnam_aware",
    "now_utc",
    "now_vietnam",
    "start_of_day_vietnam",
    "today_vietnam",
]
