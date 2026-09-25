from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import re

from ..issues import Issue


# starting values - a clinician must sign off
BOUNDS = {
    "huyet_ap_tam_thu": (Decimal("40"), Decimal("260")),
    "huyet_ap_tam_truong": (Decimal("20"), Decimal("180")),
    "chi_so_duong_huyet": (Decimal("1.0"), Decimal("40.0")),
    "chi_so_hba1c": (Decimal("3"), Decimal("20")),
    "birth_year": (1900, None),
    "visit_date": (date(2000, 1, 1), None),
}

_MEASUREMENT_RE = re.compile(
    r"^\s*([+-]?(?:(?:\d+(?:[.,]\d*)?)|(?:[.,]\d+))(?:[eE][+-]?\d+)?)"
    r"\s*([%A-Za-z][%A-Za-z0-9/]*)?\s*$"
)
_ICD_RE = re.compile(r"^[A-Z](?:10|11|12|13|14|15)(?:\.[A-Z0-9]+)?$", re.IGNORECASE)

_NUMERIC_UNIT_WHITELISTS = {
    "huyet_ap_tam_thu": {None, "mmhg"},
    "huyet_ap_tam_truong": {None, "mmhg"},
    "chi_so_hba1c": {None, "%"},
    "chi_so_duong_huyet": {None, "mmol/l", "mg/dl"},
}


def parse_measurement(raw) -> tuple[Decimal, str | None] | None:
    """Parse a finite number and an optional unit without raising."""

    try:
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (Decimal, int, float)):
            value = Decimal(str(raw))
            unit = None
        elif isinstance(raw, str):
            match = _MEASUREMENT_RE.fullmatch(raw)
            if match is None:
                return None
            value = Decimal(match.group(1).replace(",", "."))
            unit = match.group(2).lower() if match.group(2) else None
        else:
            return None
        if not value.is_finite():
            return None
        return value, unit
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None
    except Exception:
        return None


def glucose_to_mmol(raw) -> Decimal | None:
    """Return glucose in mmol/L; convert mg/dL using the specified factor."""

    try:
        parsed = parse_measurement(raw)
        if parsed is None:
            return None
        value, unit = parsed
        if unit in (None, "mmol/l"):
            return value
        if unit == "mg/dl":
            converted = value / Decimal("18.016")
            return converted if converted.is_finite() else None
        return None
    except Exception:
        return None


def check_numeric(field, raw) -> Issue | None:
    """Check one of the four supported numeric canonical fields."""

    try:
        if field not in BOUNDS or field in ("birth_year", "visit_date"):
            return Issue("INVALID", "UNKNOWN_NUMERIC_FIELD")
        parsed = parse_measurement(raw)
        if parsed is not None:
            unit = parsed[1]
            if unit not in _NUMERIC_UNIT_WHITELISTS[field]:
                return Issue("INVALID", f"INVALID_UNIT_{field.upper()}")
        if field == "chi_so_duong_huyet":
            value = glucose_to_mmol(raw)
        else:
            value = parsed[0] if parsed is not None else None
        if value is None:
            return Issue("INVALID", f"OUT_OF_RANGE_{field.upper()}")
        lower, upper = BOUNDS[field]
        if not lower <= value <= upper:
            return Issue("INVALID", f"OUT_OF_RANGE_{field.upper()}")
        return None
    except Exception:
        return Issue("INVALID", f"OUT_OF_RANGE_{str(field).upper()}")


def check_birth_year(year: int, reference_date: date) -> Issue | None:
    try:
        if (
            isinstance(year, bool)
            or not isinstance(year, int)
            or isinstance(reference_date, datetime)
            or not isinstance(reference_date, date)
        ):
            return Issue("INVALID", "BIRTH_YEAR_OUT_OF_RANGE")
        lower, _ = BOUNDS["birth_year"]
        if not lower <= year <= reference_date.year:
            return Issue("INVALID", "BIRTH_YEAR_OUT_OF_RANGE")
        return None
    except Exception:
        return Issue("INVALID", "BIRTH_YEAR_OUT_OF_RANGE")


def check_visit_date(visit: date, reference_date: date) -> Issue | None:
    try:
        if (
            isinstance(visit, datetime)
            or not isinstance(visit, date)
            or isinstance(reference_date, datetime)
            or not isinstance(reference_date, date)
        ):
            return Issue("INVALID", "VISIT_DATE_OUT_OF_RANGE")
            lower, _ = BOUNDS["visit_date"]
            if not lower <= visit <= reference_date + timedelta(days=1):
                return Issue("INVALID", "VISIT_DATE_OUT_OF_RANGE")
            return None
    except Exception:
        return Issue("INVALID", "VISIT_DATE_OUT_OF_RANGE")


def check_person_name(text) -> Issue | None:
    try:
        if not isinstance(text, str):
            return Issue("SUSPICIOUS", "NAME_INVALID_CHARS")
        if any(character.isdigit() for character in text):
            return Issue("SUSPICIOUS", "NAME_CONTAINS_DIGIT")
        allowed_punctuation = {" ", "'", ".", "-"}
        if any(
            not character.isalpha() and character not in allowed_punctuation
            for character in text
        ):
            return Issue("SUSPICIOUS", "NAME_INVALID_CHARS")
        if sum(character.isalpha() for character in text) < 2:
            return Issue("SUSPICIOUS", "NAME_TOO_SHORT")
        return None
    except Exception:
        return Issue("SUSPICIOUS", "NAME_INVALID_CHARS")


def check_icd_family(field, codes: str) -> Issue | None:
    try:
        expected = {"icd_tha": "I", "icd_dtd": "E"}.get(field)
        if expected is None or not isinstance(codes, str):
            return Issue("SUSPICIOUS", "ICD_FAMILY_MISMATCH")
        tokens = [token for token in re.split(r"[,;\s]+", codes.strip()) if token]
        if not tokens:
            return Issue("SUSPICIOUS", "ICD_FAMILY_MISMATCH")
        for token in tokens:
            if not _ICD_RE.fullmatch(token) or token[0].upper() != expected:
                return Issue("SUSPICIOUS", "ICD_FAMILY_MISMATCH")
            if expected == "E" and token[1:3] == "15":
                return Issue("SUSPICIOUS", "ICD_FAMILY_MISMATCH")
        return None
    except Exception:
        return Issue("SUSPICIOUS", "ICD_FAMILY_MISMATCH")


__all__ = [
    "parse_measurement",
    "glucose_to_mmol",
    "check_numeric",
    "check_birth_year",
    "check_visit_date",
    "check_person_name",
    "check_icd_family",
    "BOUNDS",
]
