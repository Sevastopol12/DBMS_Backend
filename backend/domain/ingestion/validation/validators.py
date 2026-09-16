"""Deterministic validators for the supported ingestion domains."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from backend.domain.ingestion.contracts import (
    IssueSeverity,
    ValidationResult,
    ValidationStatus,
)
from backend.domain.ingestion.normalization import (
    normalize_date,
    normalize_identifier,
    normalize_text,
    normalized_token,
)


def _result(
    status: ValidationStatus,
    value: Any = None,
    code: str | None = None,
    message: str | None = None,
    severity: IssueSeverity | None = None,
) -> ValidationResult:
    return ValidationResult(
        status=status,
        normalized_value=value,
        issue_code=code,
        message=message,
        severity=severity,
    )


def _missing(value: Any) -> ValidationResult | None:
    if normalize_text(value) is None:
        return _result(
            ValidationStatus.MISSING,
            None,
            "MISSING_VALUE",
            "A value was not supplied.",
            IssueSeverity.ERROR,
        )
    return None


def validate_cccd(value: Any) -> ValidationResult:
    """Validate CCCD structure without relying on other row fields."""
    if missing := _missing(value):
        return missing
    normalized = normalize_identifier(value)
    if not re.fullmatch(r"\d{12}", normalized or ""):
        return _result(
            ValidationStatus.INVALID,
            normalized,
            "INVALID_CCCD_FORMAT",
            "CCCD must contain exactly 12 digits.",
            IssueSeverity.ERROR,
        )
    province = int(normalized[:3])
    if not 1 <= province <= 96:
        return _result(
            ValidationStatus.INVALID,
            normalized,
            "INVALID_CCCD_PROVINCE",
            "CCCD province prefix must be from 001 through 096.",
            IssueSeverity.ERROR,
        )
    century_gender = normalized[3]
    mapping = {
        "0": (20, "Nam"),
        "1": (20, "Nữ"),
        "2": (21, "Nam"),
        "3": (21, "Nữ"),
        "4": (22, "Nam"),
        "5": (22, "Nữ"),
    }
    if century_gender not in mapping:
        return _result(
            ValidationStatus.INVALID,
            normalized,
            "INVALID_CCCD_CENTURY_GENDER",
            "CCCD fourth digit must encode a supported century and gender.",
            IssueSeverity.ERROR,
        )
    century, gender = mapping[century_gender]
    return ValidationResult(
        status=ValidationStatus.VALID,
        normalized_value=normalized,
        metadata={
            "province_code": normalized[:3],
            "century": century,
            "encoded_gender": gender,
            "encoded_birth_year": (century - 1) * 100 + int(normalized[4:6]),
        },
    )


def validate_bhyt(value: Any) -> ValidationResult:
    """Validate either supported BHYT representation without CCCD assumptions."""
    if missing := _missing(value):
        return missing
    normalized = (normalize_identifier(value) or "").upper()
    if re.fullmatch(r"\d{10}", normalized):
        return ValidationResult(
            status=ValidationStatus.VALID,
            normalized_value=normalized,
            metadata={"format": "NEW_10_DIGIT"},
        )
    if not re.fullmatch(r"[A-Z]{2}\d{13}", normalized):
        return _result(
            ValidationStatus.INVALID,
            normalized,
            "INVALID_BHYT_FORMAT",
            "BHYT must be 10 digits or the supported 15-character legacy format.",
            IssueSeverity.ERROR,
        )
    benefit, province = normalized[2], int(normalized[3:5])
    if benefit not in "12345":
        return _result(
            ValidationStatus.INVALID,
            normalized,
            "INVALID_BHYT_BENEFIT_LEVEL",
            "Legacy BHYT benefit level must be from 1 through 5.",
            IssueSeverity.ERROR,
        )
    if not 1 <= province <= 96:
        return _result(
            ValidationStatus.INVALID,
            normalized,
            "INVALID_BHYT_PROVINCE",
            "Legacy BHYT province code must be from 01 through 96.",
            IssueSeverity.ERROR,
        )
    return ValidationResult(
        status=ValidationStatus.VALID,
        normalized_value=normalized,
        metadata={
            "format": "LEGACY_15_CHARACTER",
            "participant_type": normalized[:2],
            "benefit_level": benefit,
            "province_code": normalized[3:5],
            "identifier": normalized[5:],
        },
    )


_GENDER = {
    "nam": "Nam",
    "m": "Nam",
    "male": "Nam",
    "nu": "Nữ",
    "f": "Nữ",
    "female": "Nữ",
}


def validate_gender(value: Any) -> ValidationResult:
    if missing := _missing(value):
        return missing
    token = normalized_token(value)
    if token in _GENDER:
        return _result(ValidationStatus.VALID, _GENDER[token])
    return _result(
        ValidationStatus.UNKNOWN,
        normalize_text(value),
        "UNKNOWN_GENDER",
        "Gender is not one of the supported explicit labels.",
        IssueSeverity.WARNING,
    )


def validate_date(value: Any) -> ValidationResult:
    if isinstance(value, datetime):
        return _result(ValidationStatus.VALID, value.date().isoformat())
    if isinstance(value, date):
        return _result(ValidationStatus.VALID, value.isoformat())
    if missing := _missing(value):
        return missing
    normalized = normalize_date(value)
    if normalized is not None:
        return _result(ValidationStatus.VALID, normalized)
    text = normalize_text(value)
    if text is not None and re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{4}", text):
        return _result(
            ValidationStatus.SUSPICIOUS,
            text,
            "AMBIGUOUS_DATE_FORMAT",
            "Date order is not established by the supported ISO-date rule.",
            IssueSeverity.WARNING,
        )
    return _result(
        ValidationStatus.INVALID,
        normalize_text(value),
        "INVALID_DATE",
        "Date must be a valid ISO calendar date (YYYY-MM-DD).",
        IssueSeverity.ERROR,
    )


def validate_blood_pressure(
    systolic: Any, diastolic: Any | None = None
) -> ValidationResult:
    """Check only structure; no clinical range or plausibility judgment is made."""
    if diastolic is None and isinstance(systolic, str) and "/" in systolic:
        parts = [part.strip() for part in systolic.split("/")]
        if len(parts) == 2:
            systolic, diastolic = parts
    if normalize_text(systolic) is None and normalize_text(diastolic) is None:
        return _result(
            ValidationStatus.MISSING,
            None,
            "MISSING_BLOOD_PRESSURE",
            "Both blood-pressure components are missing.",
            IssueSeverity.ERROR,
        )
    if normalize_text(systolic) is None or normalize_text(diastolic) is None:
        return _result(
            ValidationStatus.INVALID,
            None,
            "INCOMPLETE_BLOOD_PRESSURE",
            "Both blood-pressure components are required.",
            IssueSeverity.ERROR,
        )
    left, right = normalize_text(systolic), normalize_text(diastolic)
    if not (left and right and left.isdigit() and right.isdigit()):
        return _result(
            ValidationStatus.INVALID,
            {"huyet_ap_tam_thu": left, "huyet_ap_tam_truong": right},
            "INVALID_BLOOD_PRESSURE",
            "Blood-pressure components must be integers.",
            IssueSeverity.ERROR,
        )
    return _result(
        ValidationStatus.VALID, {"huyet_ap_tam_thu": left, "huyet_ap_tam_truong": right}
    )


def validate_icd(value: Any) -> ValidationResult:
    """Recognize a conservative ICD-like spelling without asserting medical semantics."""
    if missing := _missing(value):
        return missing
    normalized = (normalize_identifier(value) or "").upper()
    if re.fullmatch(r"[A-Z]\d{2}(?:\.[A-Z0-9]{1,4})?", normalized):
        return _result(ValidationStatus.VALID, normalized)
    return _result(
        ValidationStatus.SUSPICIOUS,
        normalized,
        "SUSPICIOUS_ICD_FORMAT",
        "ICD format is not recognized; no medical-code meaning was inferred.",
        IssueSeverity.WARNING,
    )
