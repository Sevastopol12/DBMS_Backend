"""Latest patient dimension rows used by the actionable call list."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from ..periods import localize_local, to_local_naive
from .clinical_control import (
    bp_is_controlled,
    classify_bp,
    parse_measurements,
)


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _text(value: Any) -> str | None:
    return None if _missing(value) else str(value)


def _valid_key(value: Any) -> bool:
    return not _missing(value) and str(value).strip().lower() != "nan"


def _ordered(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["_row_order"] = range(len(result))
    date_key = "ngay_kham" if "ngay_kham" in result else "_row_order"
    id_key = "id" if "id" in result else "_row_order"
    return result.sort_values(
        [date_key, id_key, "_row_order"], kind="stable", na_position="first"
    )


def _latest_valid(history: pd.DataFrame, columns: list[str]) -> pd.Series | None:
    valid = history.dropna(subset=columns)
    if valid.empty:
        return None
    return _ordered(valid).iloc[-1]


def build_patient_state(
    frame: pd.DataFrame,
    *,
    run_at: datetime,
) -> list[dict[str, Any]]:
    """Build one row per patient with latest valid value per measure."""

    if frame.empty or "patient_key" not in frame:
        return []
    work = frame.loc[frame["patient_key"].map(_valid_key)].copy()
    if work.empty:
        return []
    if not {"_systolic", "_diastolic", "_hba1c", "_glucose"}.issubset(work):
        work = parse_measurements(work)
    if "ngay_kham" in work and not pd.api.types.is_datetime64_any_dtype(
        work["ngay_kham"]
    ):
        work["ngay_kham"] = to_local_naive(
            pd.to_datetime(work["ngay_kham"], errors="coerce", format="mixed")
        )

    rows: list[dict[str, Any]] = []
    for patient_key, history in work.groupby("patient_key", sort=True, dropna=False):
        ordered = _ordered(history)
        latest = ordered.iloc[-1]
        pair = _latest_valid(history, ["_systolic", "_diastolic"])
        hba1c = _latest_valid(history, ["_hba1c"])
        glucose = _latest_valid(history, ["_glucose"])

        systolic = None if pair is None else float(pair["_systolic"])
        diastolic = None if pair is None else float(pair["_diastolic"])
        last_hba1c = None if hba1c is None else float(hba1c["_hba1c"])
        last_glucose = None if glucose is None else float(glucose["_glucose"])
        bp_controlled = None if pair is None else bp_is_controlled(systolic, diastolic)
        bp_severe = (
            None if pair is None else classify_bp(systolic, diastolic) == "severe"
        )
        hba1c_controlled = None if hba1c is None else last_hba1c < 7
        known_flags = [
            flag for flag in (bp_controlled, hba1c_controlled) if flag is not None
        ]

        visit_dates = (
            ordered["ngay_kham"].dropna()
            if "ngay_kham" in ordered
            else pd.Series(dtype=object)
        )
        last_visit = latest.get("ngay_kham")
        facility_id = latest.get("facility_id")
        if _missing(facility_id):
            facility_id = None
        rows.append(
            {
                "patient_key": str(patient_key),
                "facility_id": facility_id,
                "ho_ten": _text(latest.get("ho_ten")),
                "sdt": _text(latest.get("sdt")),
                "dia_chi": _text(latest.get("dia_chi")),
                "last_visit_date": None
                if _missing(last_visit)
                else localize_local(last_visit),
                "last_systolic": systolic,
                "last_diastolic": diastolic,
                "last_glucose": last_glucose,
                "last_hba1c": last_hba1c,
                "is_bp_controlled": bp_controlled,
                "is_bp_severe": bp_severe,
                "is_hba1c_controlled": hba1c_controlled,
                "is_out_of_control": any(not flag for flag in known_flags)
                if known_flags
                else None,
                "has_contact": bool(_text(latest.get("sdt"))),
                "first_visit_date": localize_local(visit_dates.iloc[0])
                if len(visit_dates)
                else None,
                "visit_count": len(history),
                "computed_at": run_at,
            }
        )
    return rows
