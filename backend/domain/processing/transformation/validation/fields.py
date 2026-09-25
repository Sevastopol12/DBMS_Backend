from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

from backend.database.canonical import CANONICAL_FIELD_SET
from ...identifiers_helper import classify_bhxh
from ..normalization import (
    normalize_datetime,
    normalize_identifier,
    normalize_text,
    normalized_token,
)
from ..plausibility import (
    check_birth_year,
    check_icd_family,
    check_numeric,
    check_person_name,
    check_visit_date,
    glucose_to_mmol,
    parse_measurement,
)
from ...models import RuleMode, ValidationPolicy
from .core import (
    ValidationResult,
    ValidationState,
    _canonical_decimal,
    _canonical_glucose,
    _mode,
    _plausibility_mode,
    _require_reference_date,
    _with_issue,
    text_quality,
)


_YEAR = re.compile(r"^(18|19|20|21)\d{2}$")
_ICD = re.compile(r"^[A-Z]\d{2}(?:\.\d{1,4})?$", re.I)


def _validate_cccd(
    field: str, value: Any, policy: ValidationPolicy | None
) -> ValidationResult:
    normalized = normalize_identifier(value)
    if normalized is not None and re.fullmatch(r"\d{12}", normalized):
        return ValidationResult(
            state=ValidationState.VALID, normalized_value=normalized
        )
    if normalized is not None and normalized.isdigit():
        return ValidationResult(
            state=ValidationState.SUSPICIOUS,
            issue_code="SUSPICIOUS_CCCD",
            normalized_value=normalized,
        )
    return ValidationResult(
        state=ValidationState.INVALID,
        issue_code="INVALID_CCCD",
        normalized_value=normalized,
    )


def _validate_bhyt(
    field: str, value: Any, policy: ValidationPolicy | None
) -> ValidationResult:
    normalized = normalize_identifier(value)
    compact = re.sub(r"[\s-]", "", normalized or "").upper()
    if 8 <= len(compact) <= 20 and compact.isalnum():
        result = ValidationResult(state=ValidationState.VALID, normalized_value=compact)
        mode = _mode(policy, "bhxh_era")
        if mode is not RuleMode.OFF:
            _, issue = classify_bhxh(compact)
            return _with_issue(result, mode, issue)
        return result
    return ValidationResult(
        state=ValidationState.INVALID,
        issue_code="INVALID_BHYT",
        normalized_value=normalized,
    )


def _validate_phone(
    field: str, value: Any, policy: ValidationPolicy | None
) -> ValidationResult:
    normalized = normalize_identifier(value)
    digits = re.sub(r"^\+", "", normalized or "")
    if re.fullmatch(r"\d{9,11}", digits):
        return ValidationResult(
            state=ValidationState.VALID, normalized_value=normalized
        )
    return ValidationResult(
        state=ValidationState.INVALID,
        issue_code="INVALID_PHONE",
        normalized_value=normalized,
    )


def _validate_birth_year(
    field: str, value: Any, policy: ValidationPolicy | None
) -> ValidationResult:
    normalized = normalize_text(value)
    if normalized and _YEAR.fullmatch(normalized):
        result = ValidationResult(
            state=ValidationState.VALID, normalized_value=normalized
        )
    elif normalized:
        try:
            parsed = datetime.fromisoformat(normalized)
            result = ValidationResult(
                state=ValidationState.VALID,
                normalized_value=parsed.date().isoformat(),
            )
        except ValueError:
            result = None
    else:
        result = None
    if result is not None:
        mode = _plausibility_mode(policy, field)
        if mode is not RuleMode.OFF:
            reference = _require_reference_date(policy)
            issue = check_birth_year(int(str(result.normalized_value)[:4]), reference)
            return _with_issue(result, mode, issue)
        return result
    return ValidationResult(
        state=ValidationState.INVALID,
        issue_code="INVALID_BIRTH_DATE",
        normalized_value=normalized,
    )


def _validate_visit_date(
    field: str, value: Any, policy: ValidationPolicy | None
) -> ValidationResult:
    if isinstance(value, (datetime, date)):
        result = ValidationResult(state=ValidationState.VALID, normalized_value=value)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip())
            result = ValidationResult(
                state=ValidationState.VALID, normalized_value=parsed
            )
        except (TypeError, ValueError):
            result = ValidationResult(
                state=ValidationState.INVALID,
                issue_code="INVALID_VISIT_DATE",
                normalized_value=value,
            )
    mode = _plausibility_mode(policy, field)
    if mode is not RuleMode.OFF:
        reference = _require_reference_date(policy)
        parsed = normalize_datetime(value)
        if parsed is None:
            return ValidationResult(
                state=ValidationState.INVALID,
                issue_code="INVALID_VISIT_DATE",
                normalized_value=value,
            )
        result = ValidationResult(state=ValidationState.VALID, normalized_value=parsed)
        issue = check_visit_date(parsed.date(), reference)
        return _with_issue(result, mode, issue)
    return result


def _validate_gender(
    field: str, value: Any, policy: ValidationPolicy | None
) -> ValidationResult:
    token = normalize_text(value)
    normalized = normalized_token(token)
    if normalized in {"nam", "nu", "male", "female", "m", "f"}:
        female = "\u004e\u1eef"
        canonical = "Nam" if normalized in {"nam", "male", "m"} else female
        return ValidationResult(state=ValidationState.VALID, normalized_value=canonical)
    return ValidationResult(
        state=ValidationState.INVALID,
        issue_code="INVALID_GENDER",
        normalized_value=token,
    )


def _validate_numeric(
    field: str, value: Any, policy: ValidationPolicy | None
) -> ValidationResult:
    normalized = normalize_text(value)
    legacy_result = None
    if normalized and re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", normalized):
        legacy_result = ValidationResult(
            state=ValidationState.VALID,
            normalized_value=normalized.replace(",", "."),
        )
    else:
        legacy_result = ValidationResult(
            state=ValidationState.INVALID,
            issue_code=f"INVALID_{field.upper()}",
            normalized_value=normalized,
        )
    mode = _plausibility_mode(policy, field)
    if mode is RuleMode.OFF:
        return legacy_result
    parsed = parse_measurement(value)
    if parsed is None:
        return legacy_result
    candidate = glucose_to_mmol(value) if field == "chi_so_duong_huyet" else parsed[0]
    if candidate is None:
        return legacy_result
    result = ValidationResult(
        state=ValidationState.VALID,
        normalized_value=(
            _canonical_glucose(candidate)
            if field == "chi_so_duong_huyet"
            else _canonical_decimal(candidate)
        ),
    )
    return _with_issue(result, mode, check_numeric(field, value))


def _validate_icd(
    field: str, value: Any, policy: ValidationPolicy | None
) -> ValidationResult:
    normalized = normalize_text(value)
    codes = [token for token in re.split(r"[,;|/\s]+", normalized or "") if token]
    if codes and all(_ICD.fullmatch(code) for code in codes):
        result = ValidationResult(
            state=ValidationState.VALID,
            normalized_value=", ".join(code.upper() for code in codes),
        )
        mode = _plausibility_mode(policy, field)
        if mode is not RuleMode.OFF:
            return _with_issue(
                result, mode, check_icd_family(field, result.normalized_value)
            )
        return result
    return ValidationResult(
        state=ValidationState.INVALID,
        issue_code="INVALID_ICD",
        normalized_value=normalized,
    )


def _validate_name(
    field: str, value: Any, policy: ValidationPolicy | None
) -> ValidationResult:
    result = text_quality(value, field=field)
    mode = _plausibility_mode(policy, field)
    if mode is not RuleMode.OFF and result.state is ValidationState.VALID:
        return _with_issue(result, mode, check_person_name(result.normalized_value))
    return result


_FIELD_VALIDATORS = {
    "cccd": _validate_cccd,
    "ma_bhyt": _validate_bhyt,
    "sdt": _validate_phone,
    "nam_sinh": _validate_birth_year,
    "ngay_kham": _validate_visit_date,
    "gioi_tinh": _validate_gender,
    "huyet_ap_tam_thu": _validate_numeric,
    "huyet_ap_tam_truong": _validate_numeric,
    "chi_so_duong_huyet": _validate_numeric,
    "chi_so_hba1c": _validate_numeric,
    "icd_tha": _validate_icd,
    "icd_dtd": _validate_icd,
    "ho_ten": _validate_name,
}


def validate_field(
    field: str,
    value: Any,
    *,
    policy: ValidationPolicy | None = None,
    reference_date: date | None = None,
) -> ValidationResult:
    if policy is not None and reference_date is not None:
        policy = policy.model_copy(update={"reference_date": reference_date})
    if field not in CANONICAL_FIELD_SET:
        return ValidationResult(
            state=ValidationState.UNKNOWN, issue_code="UNKNOWN_FIELD"
        )
    if value is None or (isinstance(value, str) and not value.strip()):
        return ValidationResult(state=ValidationState.MISSING, issue_code="MISSING")
    validator = _FIELD_VALIDATORS.get(field)
    if validator is None:
        return text_quality(value, field=field)
    return validator(field, value, policy)


def validate_row(values: dict[str, Any]) -> dict[str, ValidationResult]:
    return {
        field: validate_field(field, values.get(field))
        for field in sorted(CANONICAL_FIELD_SET)
    }


__all__ = ["validate_field", "validate_row"]
