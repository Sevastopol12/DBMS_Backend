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
    CanonicalField("sdt", str),
    CanonicalField("dia_chi", str),
    CanonicalField("ngay_kham", datetime, required=True),
    CanonicalField("icd_tha", str, required=True),
    CanonicalField("icd_dtd", str, required=True),
    CanonicalField("chan_doan_di_kem", str),
    CanonicalField("huyet_ap_tam_truong", str, required=True),
    CanonicalField("huyet_ap_tam_thu", str, required=True),
    CanonicalField("chi_so_duong_huyet", str, required=True),
    CanonicalField("chi_so_hba1c", str, required=True),
    CanonicalField("ghi_chu", str),
    CanonicalField("dieu_tri", str),
)

CANONICAL_FIELD_NAMES: tuple[str, ...] = tuple(field.name for field in CANONICAL_FIELDS)
CANONICAL_FIELD_SET = frozenset(CANONICAL_FIELD_NAMES)
REQUIRED_CANONICAL_FIELDS: tuple[str, ...] = tuple(
    field.name for field in CANONICAL_FIELDS if field.required
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
    "CanonicalField",
    "CANONICAL_FIELDS",
    "CANONICAL_FIELD_NAMES",
    "CANONICAL_FIELD_SET",
    "REQUIRED_CANONICAL_FIELDS",
    "ACCEPTANCE_FIELDS",
    "is_canonical_field",
    "canonical_field",
]
