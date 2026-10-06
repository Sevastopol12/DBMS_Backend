from __future__ import annotations

import hashlib
import re
from typing import Any

import pandas as pd

from backend.domain.processing.transformation.normalization import (
    normalize_identifier,
    normalized_token,
)

_CCCD_RE = re.compile(r"^\d{12}$")


def _normalize_identity_field(value: Any) -> str:
    token = normalized_token(value) or ""
    return re.sub(r"\s+", " ", token).strip()


def _normalized_cccd(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    normalized = normalize_identifier(value)
    if normalized is None or not normalized.strip():
        return None
    return normalized.strip()


def resolve_patient_key(
    cccd: Any = None,
    ho_ten: Any = None,
    nam_sinh: Any = None,
    dia_chi: Any = None,
) -> str:
    """Resolve identity from CCCD, or from the normalized fallback tuple.

    A non-empty CCCD is an identity assertion: it must be a 12-digit value.
    This deliberately raises for malformed assertions so the pipeline can
    drop only that row and report an aggregate count.
    """

    normalized_cccd = _normalized_cccd(cccd)
    if normalized_cccd is not None:
        if not _CCCD_RE.fullmatch(normalized_cccd):
            raise ValueError("invalid CCCD")
        return hashlib.sha256(f"cccd|{normalized_cccd}".encode()).hexdigest()

    parts = [_normalize_identity_field(v) for v in (ho_ten, nam_sinh, dia_chi)]
    joined = "fallback|" + "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


__all__ = ["resolve_patient_key"]
