from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from ...models import ValidationPolicy
from ..normalization import normalize_text


class ValidationState(str, Enum):
    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ValidationState
    issue_code: str | None = None
    normalized_value: Any = None


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


def plausibility_applies(policy: ValidationPolicy | None, field: str) -> bool:
    """Whether plausibility checks run for a field under the given policy."""
    if field not in _PLAUSIBILITY_FIELDS:
        return False
    if policy is None:
        return False
    return policy.plausibility_enabled


def _require_reference_date(policy: ValidationPolicy | None) -> date:
    if policy is None or policy.reference_date is None:
        raise ValueError("reference_date is required for plausibility checks")
    return policy.reference_date


def _canonical_decimal(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    return "0" if normalized in {"", "-0"} else normalized


def _canonical_glucose(value: Decimal) -> str:
    return _canonical_decimal(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def apply_issue(result: ValidationResult, issue: Any) -> ValidationResult:
    """Fold a plausibility finding into an INVALID result.

    Every formerly-flagged outcome is INVALID: a plausibility issue on a
    required field rejects the row, and on an optional field the engine
    nulls the value.
    """
    if issue is None:
        return result
    return result.model_copy(
        update={
            "state": ValidationState.INVALID,
            "issue_code": issue.code,
        }
    )


def text_quality(value: Any, *, field: str) -> ValidationResult:
    if value is None or (isinstance(value, str) and not value.strip()):
        return ValidationResult(state=ValidationState.MISSING, issue_code="MISSING")
    text = normalize_text(value)
    if text is None:
        return ValidationResult(state=ValidationState.MISSING, issue_code="MISSING")
    if _CONTROL.search(text):
        return ValidationResult(
            state=ValidationState.INVALID,
            issue_code="CONTROL_CHARACTER",
            normalized_value=text,
        )
    if _REPLACEMENT in text:
        return ValidationResult(
            state=ValidationState.INVALID,
            issue_code="REPLACEMENT_CHARACTER",
            normalized_value=text,
        )
    if len(text) > 2000:
        return ValidationResult(
            state=ValidationState.INVALID,
            issue_code="EXTREME_LENGTH",
            normalized_value=text,
        )
    if len(text) >= 8:
        symbol_count = sum(
            not (char.isalnum() or char.isspace() or char in "._,-()/") for char in text
        )
        if symbol_count / len(text) > 0.45:
            return ValidationResult(
                state=ValidationState.INVALID,
                issue_code="EXCESSIVE_SYMBOL_RATIO",
                normalized_value=text,
            )
    if (
        field in {"ho_ten", "dia_chi", "ghi_chu", "dieu_tri", "chan_doan_di_kem"}
        and len(text) > 2
    ) and not any(char.isalpha() for char in text):
        return ValidationResult(
            state=ValidationState.INVALID,
            issue_code="MALFORMED_TEXT",
            normalized_value=text,
        )
    return ValidationResult(state=ValidationState.VALID, normalized_value=text)


__all__ = [
    "ValidationResult",
    "ValidationState",
    "_canonical_decimal",
    "_canonical_glucose",
    "_require_reference_date",
    "apply_issue",
    "plausibility_applies",
    "text_quality",
]
