from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping

from .identifiers import decode_cccd
from .reference import cccd_provinces


@dataclass(frozen=True)
class CrossFieldIssue:
    fields: tuple[str, ...]
    severity: str
    code: str


def _value(values: Mapping[str, Any], field: str) -> Any:
    try:
        return values.get(field)
    except Exception:
        return None


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _birth_info(value: Any) -> tuple[int, date | None] | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, datetime):
        return value.year, value.date()
    if isinstance(value, date):
        return value.year, value
    if not isinstance(value, str):
        return None

    text = value.strip()
    if re.fullmatch(r"\d{4}", text):
        return int(text), None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        try:
            parsed_date = date.fromisoformat(text)
        except (TypeError, ValueError):
            return None
        return parsed_date.year, parsed_date
    return parsed.year, parsed.date()


def _visit_date(value: Any) -> date | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        try:
            return date.fromisoformat(text)
        except (TypeError, ValueError):
            return None


def _gender(value: Any) -> str | None:
    if not isinstance(value, str) or value.strip().casefold() not in {"nam", "nữ", "nu"}:
        return None
    normalized = value.strip().casefold()
    return "Nam" if normalized == "nam" else "Nữ"


def check_row(values: Mapping[str, Any], *, reference_date: date) -> list[CrossFieldIssue]:
    """Return PHI-safe cross-field findings; malformed inputs are skipped."""

    try:
        issues: list[CrossFieldIssue] = []

        systolic = _decimal(_value(values, "huyet_ap_tam_thu"))
        diastolic = _decimal(_value(values, "huyet_ap_tam_truong"))
        if systolic is not None and diastolic is not None and systolic <= diastolic:
            issues.append(
                CrossFieldIssue(
                    fields=("huyet_ap_tam_thu", "huyet_ap_tam_truong"),
                    severity="SUSPICIOUS",
                    code="BP_SYSTOLIC_NOT_ABOVE_DIASTOLIC",
                )
            )

        raw_cccd = _value(values, "cccd")
        decoded = decode_cccd(raw_cccd)
        if isinstance(raw_cccd, str) and re.fullmatch(r"\d{12}", raw_cccd) is not None:
            if cccd_provinces.PROVINCE_CODES and raw_cccd[:3] not in cccd_provinces.PROVINCE_CODES:
                issues.append(
                    CrossFieldIssue(
                        fields=("cccd",),
                        severity="SUSPICIOUS",
                        code="CCCD_PROVINCE_UNKNOWN",
                    )
                )
            if decoded is None:
                issues.append(
                    CrossFieldIssue(
                        fields=("cccd",),
                        severity="SUSPICIOUS",
                        code="CCCD_UNDECODABLE",
                    )
                )
        if decoded is not None:
            birth = _birth_info(_value(values, "nam_sinh"))
            if birth is not None and birth[0] != decoded.birth_year:
                issues.append(
                    CrossFieldIssue(
                        fields=("cccd", "nam_sinh"),
                        severity="SUSPICIOUS",
                        code="CCCD_BIRTH_YEAR_MISMATCH",
                    )
                )
            gender = _gender(_value(values, "gioi_tinh"))
            if gender is not None and gender != decoded.gender:
                issues.append(
                    CrossFieldIssue(
                        fields=("cccd", "gioi_tinh"),
                        severity="SUSPICIOUS",
                        code="CCCD_GENDER_MISMATCH",
                    )
                )

        birth = _birth_info(_value(values, "nam_sinh"))
        visit = _visit_date(_value(values, "ngay_kham"))
        if birth is not None and visit is not None:
            birth_date = birth[1]
            before_birth = visit < birth_date if birth_date is not None else visit.year < birth[0]
            if before_birth:
                issues.append(
                    CrossFieldIssue(
                        fields=("ngay_kham", "nam_sinh"),
                        severity="INVALID",
                        code="VISIT_BEFORE_BIRTH",
                    )
                )
        return issues
    except Exception:
        return []


__all__ = ["CrossFieldIssue", "check_row"]
