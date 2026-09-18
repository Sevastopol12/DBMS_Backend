"""Non-semantic, lossless-safe value normalization helpers.

These helpers return only a normalized representation.  Callers retain the
original value when reporting quality outcomes.
"""

from __future__ import annotations

from datetime import date, datetime
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
    """Return an ISO calendar date only after a successful unambiguous parse."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = normalize_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
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
