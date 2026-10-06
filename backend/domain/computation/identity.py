from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import UUID

import pandas as pd

from backend.domain.processing.transformation.normalization import (
    normalize_identifier,
)

_CCCD_RE = re.compile(r"^\d{12}$")


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


def resolve_patient_key(facility_id: UUID | str, cccd: Any) -> str:
    """Resolve the facility-scoped patient identity (D-10).

    ``patient_key = sha256("facility|{facility_id}|cccd|{cccd}")``. There is
    no fallback identity: a missing or malformed CCCD raises ``ValueError``
    so the pipeline can drop only that row and report an aggregate count.
    """

    if facility_id is None or (
        isinstance(facility_id, str) and not facility_id.strip()
    ):
        raise ValueError("missing facility_id")
    normalized_cccd = _normalized_cccd(cccd)
    if normalized_cccd is None or not _CCCD_RE.fullmatch(normalized_cccd):
        raise ValueError("invalid CCCD")
    return hashlib.sha256(
        f"facility|{facility_id}|cccd|{normalized_cccd}".encode()
    ).hexdigest()


__all__ = ["resolve_patient_key"]
