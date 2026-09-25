from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..normalization import normalize_text
from ...models import RuleMode, ValidationPolicy


class ValidationState(str, Enum):
    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"
    SUSPICIOUS = "SUSPICIOUS"
    UNKNOWN = "UNKNOWN"


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ValidationState
    issue_code: str | None = None
    normalized_value: Any = None
    flags: list[str] = Field(default_factory=list)


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REPLACEMENT = "\ufffd"

_PLAUSIBILITY_FIELDS = {
    "ngay_kham",
    "nam_sinh",
    "huyet_ap_tam_thu",
    "huyet_ap_tam_truong",
    "chi_so_duong_huyet",
    "chi_so_hba1c",
    "ho_ten",
    "icd_tha",
    "icd_dtd",
}


def _mode(policy: ValidationPolicy | None, name: str) -> RuleMode:
    if policy is None:
        return RuleMode.OFF
    return getattr(policy, name)


def _require_reference_date(policy: ValidationPolicy | None) -> date:
    if policy is None or policy.reference_date is None:
        raise ValueError("reference_date is required for plausibility checks")
    return policy.reference_date


def _canonical_decimal(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    return "0" if normalized in {"", "-0"} else normalized


def _canonical_glucose(value: Decimal) -> str:
    return _canonical_decimal(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _with_issue(
    result: ValidationResult, mode: RuleMode, issue: Any
) -> ValidationResult:
    if issue is None or mode is RuleMode.OFF:
        return result
    if mode is RuleMode.FLAG:
        if issue.code in result.flags:
            return result
        return result.model_copy(update={"flags": [*result.flags, issue.code]})
    return result.model_copy(
        update={
            "state": ValidationState(issue.severity),
            "issue_code": issue.code,
        }
    )


def _plausibility_mode(policy: ValidationPolicy | None, field: str) -> RuleMode:
    if field not in _PLAUSIBILITY_FIELDS:
        return RuleMode.OFF
    return _mode(policy, "plausibility")


def _missing(value: Any) -> ValidationResult:
    """Return the declared result type; never a bare boolean."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return ValidationResult(state=ValidationState.MISSING, issue_code="MISSING")
    return ValidationResult(state=ValidationState.UNKNOWN, issue_code="NOT_MISSING")


def text_quality(value: Any, *, field: str) -> ValidationResult:
    missing = _missing(value)
    if missing.state is ValidationState.MISSING:
        return missing
    text = normalize_text(value)
    if text is None:
        return missing
    if _CONTROL.search(text):
        return ValidationResult(
            state=ValidationState.SUSPICIOUS,
            issue_code="CONTROL_CHARACTER",
            normalized_value=text,
        )
    if _REPLACEMENT in text:
        return ValidationResult(
            state=ValidationState.SUSPICIOUS,
            issue_code="REPLACEMENT_CHARACTER",
            normalized_value=text,
        )
    if len(text) > 2000:
        return ValidationResult(
            state=ValidationState.SUSPICIOUS,
            issue_code="EXTREME_LENGTH",
            normalized_value=text,
        )
    if len(text) >= 8:
        symbol_count = sum(
            not (char.isalnum() or char.isspace() or char in "._,-()/") for char in text
        )
        if symbol_count / len(text) > 0.45:
            return ValidationResult(
                state=ValidationState.SUSPICIOUS,
                issue_code="EXCESSIVE_SYMBOL_RATIO",
                normalized_value=text,
            )
    if (
        field in {"ho_ten", "dia_chi", "ghi_chu", "dieu_tri", "chan_doan_di_kem"}
        and len(text) > 2
    ):
        if not any(char.isalpha() for char in text):
            return ValidationResult(
                state=ValidationState.SUSPICIOUS,
                issue_code="MALFORMED_TEXT",
                normalized_value=text,
            )
    return ValidationResult(state=ValidationState.VALID, normalized_value=text)


__all__ = [
    "ValidationResult",
    "ValidationState",
    "text_quality",
]
