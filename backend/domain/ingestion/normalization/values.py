"""Non-semantic, lossless-safe value normalization helpers.

These helpers return only a normalized representation.  Callers retain the
original value when reporting quality outcomes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from .lexical import clean_optional_text


def normalize_text(value: Any, *, collapse_whitespace: bool = True) -> str | None:
    """Trim text and, when requested, reduce runs of whitespace to one space."""
    text = clean_optional_text(value)
    return (
        re.sub(r"\s+", " ", text) if text is not None and collapse_whitespace else text
    )


def normalize_identifier(value: Any) -> str | None:
    """Trim an identifier without removing zeroes or altering its characters."""
    return normalize_text(value, collapse_whitespace=False)


def normalize_date(value: Any) -> str | None:
    """Return an ISO date from common spreadsheet date representations."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number = float(value)
        if number.is_integer() and 10_000_000 <= number <= 99_999_999:
            try:
                return datetime.strptime(str(int(number)), "%Y%m%d").date().isoformat()
            except ValueError:
                return None
        if 1 <= number <= 60_000:
            try:
                return (datetime(1899, 12, 30) + timedelta(days=number)).date().isoformat()
            except (OverflowError, ValueError):
                return None
    text = normalize_text(value)
    if text is None:
        return None
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    for parser in (
        date.fromisoformat,
        lambda candidate: datetime.strptime(candidate, "%d/%m/%Y").date(),
        lambda candidate: datetime.strptime(candidate, "%d-%m-%Y").date(),
        lambda candidate: datetime.strptime(candidate, "%Y/%m/%d").date(),
        lambda candidate: datetime.strptime(candidate, "%d/%m/%Y %H:%M").date(),
        lambda candidate: datetime.strptime(candidate, "%d/%m/%Y %H:%M:%S").date(),
        lambda candidate: datetime.strptime(candidate, "%d-%m-%Y %H:%M").date(),
        lambda candidate: datetime.strptime(candidate, "%d-%m-%Y %H:%M:%S").date(),
        lambda candidate: datetime.strptime(candidate, "%Y/%m/%d %H:%M").date(),
        lambda candidate: datetime.strptime(candidate, "%Y/%m/%d %H:%M:%S").date(),
    ):
        try:
            return parser(text).isoformat()
        except ValueError:
            continue
    return None


def normalize_datetime(value: Any) -> datetime | None:
    """Return a datetime from supported spreadsheet and ISO representations."""
    try:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            number = float(value)
            if number.is_integer() and 10_000_000 <= number <= 99_999_999:
                try:
                    return datetime.strptime(str(int(number)), "%Y%m%d")
                except ValueError:
                    return None
            if 1 <= number <= 60_000:
                return datetime(1899, 12, 30) + timedelta(days=number)

        text = normalize_text(value)
        if text is None:
            return None
        if re.fullmatch(r"\d{8}", text):
            try:
                return datetime.strptime(text, "%Y%m%d")
            except ValueError:
                return None
        for parser in (
            datetime.fromisoformat,
            lambda candidate: datetime.strptime(candidate, "%d/%m/%Y"),
            lambda candidate: datetime.strptime(candidate, "%d/%m/%Y %H:%M"),
            lambda candidate: datetime.strptime(candidate, "%d/%m/%Y %H:%M:%S"),
            lambda candidate: datetime.strptime(candidate, "%d-%m-%Y"),
            lambda candidate: datetime.strptime(candidate, "%d-%m-%Y %H:%M"),
            lambda candidate: datetime.strptime(candidate, "%d-%m-%Y %H:%M:%S"),
            lambda candidate: datetime.strptime(candidate, "%Y/%m/%d"),
            lambda candidate: datetime.strptime(candidate, "%Y/%m/%d %H:%M"),
            lambda candidate: datetime.strptime(candidate, "%Y/%m/%d %H:%M:%S"),
        ):
            try:
                return parser(text)
            except ValueError:
                continue
    except Exception:
        return None
    return None


def normalize_numeric(value: Any) -> str | None:
    """Canonicalize a plain decimal spelling without applying a unit or scale.

    Thousands separators are intentionally not interpreted: their meaning is
    locale-dependent and therefore belongs in a caller-supplied rule.
    """
    text = normalize_text(value)
    if text is None:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    normalized = format(number.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return "0" if normalized in {"", "-0"} else normalized


def normalize_measurement(value: Any) -> str | None:
    """Normalize a scalar measurement without coercing identifiers."""
    text = normalize_text(value)
    if text is None:
        return None
    if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", text):
        return text.replace(",", ".")
    return normalize_numeric(text)


__all__ = [
    "normalize_text",
    "normalize_identifier",
    "normalize_date",
    "normalize_datetime",
    "normalize_numeric",
    "normalize_measurement",
]
