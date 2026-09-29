from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

VIETNAM_TZ_NAME = "Asia/Ho_Chi_Minh"
VIETNAM_TZ = ZoneInfo(VIETNAM_TZ_NAME)
UTC = timezone.utc


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


__all__ = [
    "UTC",
    "VIETNAM_TZ",
    "VIETNAM_TZ_NAME",
    "ensure_vietnam_aware",
    "now_utc",
    "now_vietnam",
    "today_vietnam",
]
