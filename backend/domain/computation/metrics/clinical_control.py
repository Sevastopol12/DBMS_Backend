"""Clinical control aggregates with the canonical measurement parsers."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.domain.processing.transformation.plausibility import (
    glucose_to_mmol,
    parse_measurement,
)


def _scalar(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


def _measurement(value: Any) -> float | None:
    parsed = parse_measurement(_scalar(value))
    return float(parsed[0]) if parsed is not None else None


def _glucose(value: Any) -> float | None:
    parsed = glucose_to_mmol(_scalar(value))
    return float(parsed) if parsed is not None else None


def coerce_glucose_mmol(series: pd.Series) -> pd.Series:
    """Convert a raw glucose series to mmol/L using the shared parser."""

    return series.map(_glucose, na_action=None)


def coerce_bp_or_hba1c(series: pd.Series) -> pd.Series:
    """Parse a raw BP/HbA1c series without silently dropping unit suffixes."""

    return series.map(_measurement, na_action=None)


def _values(frame: pd.DataFrame, field: str, *, glucose: bool = False) -> pd.Series:
    if field not in frame:
        return pd.Series(dtype="float64")
    converted = (
        coerce_glucose_mmol(frame[field])
        if glucose
        else coerce_bp_or_hba1c(frame[field])
    )
    return converted.dropna().astype(float)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _bp_stage(systolic: float, diastolic: float) -> str:
    # starting values - a clinician must sign off
    if systolic > 180 or diastolic > 120:
        return "crisis"
    if systolic >= 140 or diastolic >= 90:
        return "stage_2"
    if systolic >= 120 or diastolic >= 80:
        return "stage_1"
    return "normal"


def compute_clinical_control(frame: pd.DataFrame) -> dict[str, float | int | None]:
    """Return BP staging/control and glycemic statistics for one slice."""

    systolic = (
        coerce_bp_or_hba1c(frame["huyet_ap_tam_thu"])
        if "huyet_ap_tam_thu" in frame
        else pd.Series(index=frame.index, dtype="float64")
    )
    diastolic = (
        coerce_bp_or_hba1c(frame["huyet_ap_tam_truong"])
        if "huyet_ap_tam_truong" in frame
        else pd.Series(index=frame.index, dtype="float64")
    )
    bp = pd.DataFrame({"systolic": systolic, "diastolic": diastolic}).dropna()
    controlled = (bp["systolic"] < 140) & (bp["diastolic"] < 90)
    stages = [
        _bp_stage(float(row.systolic), float(row.diastolic))
        for row in bp.itertuples(index=False)
    ]

    glucose = _values(frame, "chi_so_duong_huyet", glucose=True)
    hba1c = _values(frame, "chi_so_hba1c")
    return {
        "bp_control_rate": _ratio(int(controlled.sum()), len(bp)),
        "bp_stage_normal_count": stages.count("normal"),
        "bp_stage_1_count": stages.count("stage_1"),
        "bp_stage_2_count": stages.count("stage_2"),
        "bp_stage_crisis_count": stages.count("crisis"),
        "glycemic_control_rate": _ratio(int((hba1c < 7).sum()), len(hba1c)),
        "avg_glucose": float(glucose.mean()) if len(glucose) else None,
        "median_glucose": float(glucose.median()) if len(glucose) else None,
        "avg_hba1c": float(hba1c.mean()) if len(hba1c) else None,
        "median_hba1c": float(hba1c.median()) if len(hba1c) else None,
    }


__all__ = [
    "coerce_bp_or_hba1c",
    "coerce_glucose_mmol",
    "compute_clinical_control",
]
