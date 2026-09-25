from dataclasses import dataclass
import re
from typing import Literal

from .issues import Issue


@dataclass(frozen=True)
class CccdDecode:
    province_code: str
    gender: Literal["Nam", "Nữ"]
    birth_year: int


def decode_cccd(text: object) -> CccdDecode | None:
    """Decode the structural century, gender, and birth year digits of a CCCD."""

    if not isinstance(text, str) or re.fullmatch(r"\d{12}", text) is None:
        return None

    century_gender = text[3]
    if century_gender not in "0123":
        return None

    century = 1900 if century_gender in "01" else 2000
    gender: Literal["Nam", "Nữ"] = "Nam" if century_gender in "02" else "Nữ"
    return CccdDecode(
        province_code=text[:3],
        gender=gender,
        birth_year=century + int(text[4:6]),
    )


def classify_bhxh(raw: object) -> tuple[str, Issue | None]:
    """Classify a BHXH/BHYT identifier without asserting legacy validity."""

    if not isinstance(raw, str):
        return "unknown", Issue("INVALID", "INVALID_BHYT")

    compact = re.sub(r"[\s-]", "", raw).upper()
    if re.fullmatch(r"\d{10}", compact):
        return "current_10digit", None
    if re.fullmatch(r"[A-Z]{2}\d{13}", compact):
        return "legacy_15char", None
    if re.fullmatch(r"[A-Z0-9]{8,20}", compact):
        return "legacy_unverified", Issue("SUSPICIOUS", "LEGACY_BHXH_UNVERIFIED")
    return "unknown", Issue("INVALID", "INVALID_BHYT")


__all__ = ["CccdDecode", "Issue", "classify_bhxh", "decode_cccd"]
