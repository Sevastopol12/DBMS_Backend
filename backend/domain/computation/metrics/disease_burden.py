"""Disease flags and heuristic free-text comorbidity metrics."""

from __future__ import annotations

import re

import pandas as pd

from backend.domain.processing.transformation.normalization import normalized_token


def _present_series(frame: pd.DataFrame, field: str) -> pd.Series:
    if field not in frame:
        return pd.Series(False, index=frame.index, dtype=bool)
    values = frame[field]
    return (
        values.notna()
        & values.astype(str).str.strip().ne("")
        & values.astype(str).ne("nan")
    )


def _patient_series(frame: pd.DataFrame) -> pd.Series:
    if "patient_key" in frame:
        values = frame["patient_key"].astype("string")
        return values.where(values.notna() & values.ne("nan"), frame.index.astype(str))
    return pd.Series(frame.index.astype(str), index=frame.index, dtype="string")


def compute_disease_burden(frame: pd.DataFrame) -> dict[str, float | None]:
    """Return distinct-patient disease percentages for codes in this slice."""

    if frame.empty:
        return {"pct_tha": None, "pct_dtd": None, "pct_comorbid": None}
    grouped = (
        pd.DataFrame(
            {
                "patient_key": _patient_series(frame),
                "tha": _present_series(frame, "icd_tha").to_numpy(),
                "dtd": _present_series(frame, "icd_dtd").to_numpy(),
            },
            index=frame.index,
        )
        .groupby("patient_key", sort=False)[["tha", "dtd"]]
        .any()
    )
    total = len(grouped)
    if not total:
        return {"pct_tha": None, "pct_dtd": None, "pct_comorbid": None}
    return {
        "pct_tha": float(grouped["tha"].sum() / total),
        "pct_dtd": float(grouped["dtd"].sum() / total),
        "pct_comorbid": float((grouped["tha"] & grouped["dtd"]).sum() / total),
    }


def _diagnosis_tokens(value: object) -> list[str]:
    if value is None:
        return []
    try:
        if bool(pd.isna(value)):
            return []
    except (TypeError, ValueError):
        pass
    if not str(value).strip():
        return []
    normalized = normalized_token(value) or ""
    return [
        token
        for token in (
            re.sub(r"\s+", " ", raw).strip() for raw in re.split(r"[,;/]", normalized)
        )
        if token
    ]


def compute_comorbidity_breakdown(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Count distinct patients per heuristic comorbidity token."""

    if frame.empty:
        return []
    keys = _patient_series(frame).tolist()
    values = (
        frame["chan_doan_di_kem"].tolist()
        if "chan_doan_di_kem" in frame
        else [None] * len(frame)
    )
    patients_by_label: dict[str, set[str]] = {}
    for key, value in zip(keys, values, strict=False):
        for label in set(_diagnosis_tokens(value)):
            patients_by_label.setdefault(label, set()).add(str(key))
    return [
        {"diagnosis_label": label, "patient_count": len(patients)}
        for label, patients in sorted(patients_by_label.items())
    ]
