"""Disease flags and heuristic free-text comorbidity metrics."""

from __future__ import annotations

import re

import pandas as pd

from backend.domain.processing.transformation.normalization import normalized_token


def _patient_key(row: pd.Series, fallback: object) -> str:
    value = row.get("patient_key")
    return str(value) if pd.notna(value) else str(fallback)


def _present(value: object) -> bool:
    if value is None:
        return False
    try:
        return not bool(pd.isna(value)) and bool(str(value).strip())
    except (TypeError, ValueError):
        return bool(str(value).strip())


def compute_disease_burden(frame: pd.DataFrame) -> dict[str, float | None]:
    """Return THA/diabetes/comorbidity percentages over unique patients."""

    patient_flags: dict[str, list[bool]] = {}
    for index, row in frame.iterrows():
        key = _patient_key(row, index)
        flags = patient_flags.setdefault(key, [False, False])
        flags[0] |= _present(row.get("icd_tha"))
        flags[1] |= _present(row.get("icd_dtd"))

    if not patient_flags:
        return {"pct_tha": None, "pct_dtd": None, "pct_comorbid": None}
    total = len(patient_flags)
    tha = sum(flags[0] for flags in patient_flags.values())
    dtd = sum(flags[1] for flags in patient_flags.values())
    comorbid = sum(flags[0] and flags[1] for flags in patient_flags.values())
    return {
        "pct_tha": tha / total,
        "pct_dtd": dtd / total,
        "pct_comorbid": comorbid / total,
    }


def _diagnosis_tokens(value: object) -> list[str]:
    if not _present(value):
        return []
    normalized = normalized_token(value) or ""
    return [
        token
        for token in (re.sub(r"\s+", " ", raw).strip() for raw in re.split(r"[,;/]", normalized))
        if token
    ]


def compute_comorbidity_breakdown(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Count distinct patients per heuristic comorbidity token.

    This tokenization is heuristic, not authoritative: ``chan_doan_di_kem``
    is free text and is not a controlled diagnosis vocabulary.
    """

    patients_by_label: dict[str, set[str]] = {}
    for index, row in frame.iterrows():
        key = _patient_key(row, index)
        for label in set(_diagnosis_tokens(row.get("chan_doan_di_kem"))):
            patients_by_label.setdefault(label, set()).add(key)
    return [
        {"diagnosis_label": label, "patient_count": len(patients)}
        for label, patients in sorted(patients_by_label.items())
    ]
