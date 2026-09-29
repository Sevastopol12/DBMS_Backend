from __future__ import annotations

import hashlib
import re

import pandas as pd

from backend.domain.processing.transformation.normalization import normalized_token


def _normalize_identity_field(value) -> str:
    token = normalized_token(value) or ""
    return re.sub(r"\s+", " ", token).strip()


def resolve_patient_key(ho_ten, nam_sinh, dia_chi) -> str:
    """Hash the normalized name, birth year, and address identity tuple."""

    parts = [_normalize_identity_field(v) for v in (ho_ten, nam_sinh, dia_chi)]
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def add_patient_key(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with the contract identity hash in ``patient_key``."""

    result = frame.copy()
    result["patient_key"] = result.apply(
        lambda row: resolve_patient_key(
            row.get("ho_ten"), row.get("nam_sinh"), row.get("dia_chi")
        ),
        axis=1,
    )
    return result


__all__ = ["add_patient_key", "resolve_patient_key"]
