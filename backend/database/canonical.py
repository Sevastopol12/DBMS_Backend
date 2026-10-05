"""The single source of truth for canonical report fields.

Mapping, validation, persistence and quality reporting all use this contract.
Keep changes to the canonical report schema in this module first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CanonicalField:
    name: str
    value_type: type[Any]
    required: bool = False


CANONICAL_FIELDS: tuple[CanonicalField, ...] = (
    CanonicalField("ma_bhyt", str),
    CanonicalField("cccd", str, required=True),
    CanonicalField("ho_ten", str, required=True),
    CanonicalField("gioi_tinh", str),
    CanonicalField("nam_sinh", str, required=True),
    CanonicalField("sdt", str, required=True),
    CanonicalField("dia_chi", str),
    CanonicalField("ngay_kham", datetime, required=True),
    CanonicalField("icd_tha", str),
    CanonicalField("icd_dtd", str),
    CanonicalField("chan_doan_di_kem", str),
    CanonicalField("huyet_ap_tam_truong", str),
    CanonicalField("huyet_ap_tam_thu", str),
    CanonicalField("chi_so_duong_huyet", str),
    CanonicalField("chi_so_hba1c", str),
    CanonicalField("ghi_chu", str),
    CanonicalField("dieu_tri", str),
)

CANONICAL_FIELD_NAMES: tuple[str, ...] = tuple(field.name for field in CANONICAL_FIELDS)
CANONICAL_FIELD_SET = frozenset(CANONICAL_FIELD_NAMES)
REQUIRED_CANONICAL_FIELDS: tuple[str, ...] = tuple(
    field.name for field in CANONICAL_FIELDS if field.required
)
OPTIONAL_CLINICAL_FIELDS: tuple[str, ...] = (
    "icd_tha",
    "icd_dtd",
    "huyet_ap_tam_truong",
    "huyet_ap_tam_thu",
    "chi_so_duong_huyet",
    "chi_so_hba1c",
)
# A row is eligible for production only when every required canonical value
# is valid. Keep this as the sole source of truth for row acceptance.
ACCEPTANCE_FIELDS: tuple[str, ...] = REQUIRED_CANONICAL_FIELDS


def is_canonical_field(name: str) -> bool:
    return name in CANONICAL_FIELD_SET


def canonical_field(name: str) -> CanonicalField:
    for field in CANONICAL_FIELDS:
        if field.name == name:
            return field
    raise KeyError(f"Unknown canonical field: {name}")


__all__ = [
    "ACCEPTANCE_FIELDS",
    "CANONICAL_FIELDS",
    "CANONICAL_FIELD_NAMES",
    "CANONICAL_FIELD_SET",
    "OPTIONAL_CLINICAL_FIELDS",
    "REQUIRED_CANONICAL_FIELDS",
    "CanonicalField",
    "canonical_field",
    "is_canonical_field",
]
