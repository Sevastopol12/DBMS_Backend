"""Patient-level clinical aggregates using the canonical parsers."""

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
    return series.map(_glucose, na_action=None).astype("float64")


def coerce_bp_or_hba1c(series: pd.Series) -> pd.Series:
    return series.map(_measurement, na_action=None).astype("float64")


def parse_measurements(frame: pd.DataFrame) -> pd.DataFrame:
    """Parse all four clinical measurements once and retain them as columns."""

    result = frame.copy()
    result["_systolic"] = (
        coerce_bp_or_hba1c(result["huyet_ap_tam_thu"])
        if "huyet_ap_tam_thu" in result
        else pd.Series(float("nan"), index=result.index)
    )
    result["_diastolic"] = (
        coerce_bp_or_hba1c(result["huyet_ap_tam_truong"])
        if "huyet_ap_tam_truong" in result
        else pd.Series(float("nan"), index=result.index)
    )
    result["_hba1c"] = (
        coerce_bp_or_hba1c(result["chi_so_hba1c"])
        if "chi_so_hba1c" in result
        else pd.Series(float("nan"), index=result.index)
    )
    result["_glucose"] = (
        coerce_glucose_mmol(result["chi_so_duong_huyet"])
        if "chi_so_duong_huyet" in result
        else pd.Series(float("nan"), index=result.index)
    )
    return result


def classify_bp(systolic: float, diastolic: float) -> str:
    """Classify one valid BP pair using the five cut-point stages."""

    systolic = float(systolic)
    diastolic = float(diastolic)
    # starting values - a clinician must sign off
    if systolic > 180 or diastolic > 120:
        return "severe"
    if systolic >= 140 or diastolic >= 90:
        return "stage_2"
    if systolic >= 130 or diastolic >= 80:
        return "stage_1"
    if systolic >= 120:
        return "elevated"
    return "normal"


def bp_is_controlled(systolic: float, diastolic: float) -> bool:
    return float(systolic) < 140 and float(diastolic) < 90


def _keys(frame: pd.DataFrame) -> pd.Series:
    if "patient_key" in frame:
        values = frame["patient_key"].astype("string")
        return values.where(values.notna() & values.ne("nan"), frame.index.astype(str))
    return pd.Series(frame.index.astype(str), index=frame.index, dtype="string")


def _ordered(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["_patient_key"] = _keys(result).to_numpy()
    result["_row_order"] = range(len(result))
    date_key = "ngay_kham" if "ngay_kham" in result else "_row_order"
    id_key = "id" if "id" in result else "_row_order"
    return result.sort_values([date_key, id_key, "_row_order"], kind="stable", na_position="first")


def _latest_valid_pair(frame: pd.DataFrame) -> pd.DataFrame:
    valid = frame.dropna(subset=["_systolic", "_diastolic"])
    if valid.empty:
        return valid
    return _ordered(valid).drop_duplicates("_patient_key", keep="last")


def compute_bp_metrics(frame: pd.DataFrame) -> dict[str, float | int | None]:
    if not {"_systolic", "_diastolic"}.issubset(frame):
        frame = parse_measurements(frame)
    reps = _latest_valid_pair(frame)
    if reps.empty:
        return {
            "bp_control_rate": None,
            "bp_stage_normal_count": 0,
            "bp_stage_elevated_count": 0,
            "bp_stage_1_count": 0,
            "bp_stage_2_count": 0,
            "bp_stage_severe_count": 0,
        }
    controlled = reps.apply(
        lambda row: bp_is_controlled(row["_systolic"], row["_diastolic"]), axis=1
    )
    stages = reps.apply(
        lambda row: classify_bp(row["_systolic"], row["_diastolic"]), axis=1
    )
    return {
        "bp_control_rate": float(controlled.mean()),
        "bp_stage_normal_count": int(stages.eq("normal").sum()),
        "bp_stage_elevated_count": int(stages.eq("elevated").sum()),
        "bp_stage_1_count": int(stages.eq("stage_1").sum()),
        "bp_stage_2_count": int(stages.eq("stage_2").sum()),
        "bp_stage_severe_count": int(stages.eq("severe").sum()),
    }


def _present(frame: pd.DataFrame, field: str) -> pd.Series:
    if field not in frame:
        return pd.Series(False, index=frame.index, dtype=bool)
    values = frame[field]
    return values.notna() & values.astype(str).str.strip().ne("") & values.astype(str).ne("nan")


def compute_glycemic_metrics(frame: pd.DataFrame) -> dict[str, float | None]:
    if not {"_hba1c", "_glucose"}.issubset(frame):
        frame = parse_measurements(frame)
    cohort_keys = set(_keys(frame.loc[_present(frame, "icd_dtd")]).tolist())
    cohort = frame.copy()
    cohort["_patient_key"] = _keys(cohort).to_numpy()
    cohort = cohort.loc[cohort["_patient_key"].isin(cohort_keys)]
    valid_hba1c = cohort.dropna(subset=["_hba1c"])
    hba1c_reps = (
        _ordered(valid_hba1c).drop_duplicates("_patient_key", keep="last")
        if not valid_hba1c.empty
        else valid_hba1c
    )
    glucose = frame["_glucose"].dropna() if "_glucose" in frame else pd.Series(dtype=float)
    return {
        "glycemic_control_rate": (
            float((hba1c_reps["_hba1c"] < 7).mean())
            if not hba1c_reps.empty
            else None
        ),
        "avg_glucose": float(glucose.mean()) if not glucose.empty else None,
        "median_glucose": float(glucose.median()) if not glucose.empty else None,
        "avg_hba1c": float(hba1c_reps["_hba1c"].mean()) if not hba1c_reps.empty else None,
        "median_hba1c": float(hba1c_reps["_hba1c"].median()) if not hba1c_reps.empty else None,
    }


def compute_clinical_control(frame: pd.DataFrame) -> dict[str, float | int | None]:
    work = frame if {"_systolic", "_diastolic", "_hba1c", "_glucose"}.issubset(frame) else parse_measurements(frame)
    return {**compute_bp_metrics(work), **compute_glycemic_metrics(work)}


__all__ = [
    "bp_is_controlled",
    "classify_bp",
    "coerce_bp_or_hba1c",
    "coerce_glucose_mmol",
    "compute_bp_metrics",
    "compute_clinical_control",
    "compute_glycemic_metrics",
    "parse_measurements",
]
