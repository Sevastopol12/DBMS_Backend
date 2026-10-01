"""Latest patient dimension rows used by the actionable call list."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from ..bucketing import localize_local, to_local_naive
from .clinical_control import _glucose, _measurement


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _text(value: Any) -> str | None:
    return None if _missing(value) else str(value)


def _valid_patient_key(value: Any) -> bool:
    if _missing(value):
        return False
    return str(value).strip().lower() != "nan"


def _latest_flags(
    systolic: float | None,
    diastolic: float | None,
    hba1c: float | None,
) -> tuple[bool | None, bool | None, bool | None, bool | None]:
    bp_controlled = None
    bp_crisis = None
    if systolic is not None and diastolic is not None:
        bp_controlled = systolic < 140 and diastolic < 90
        bp_crisis = systolic > 180 or diastolic > 120
    hba1c_controlled = None if hba1c is None else hba1c < 7
    checks = [flag for flag in (bp_controlled, hba1c_controlled) if flag is not None]
    out_of_control = any(not flag for flag in checks) if checks else None
    return bp_controlled, bp_crisis, hba1c_controlled, out_of_control


def build_patient_state(
    frame: pd.DataFrame,
    *,
    run_at: datetime,
) -> list[dict[str, Any]]:
    """Build one latest-visit state row per patient key."""

    if frame.empty or "patient_key" not in frame:
        return []
    work = frame.copy()
    work = work.loc[work["patient_key"].map(_valid_patient_key)].copy()
    if work.empty:
        return []
    work["_visit_sort"] = to_local_naive(
        pd.to_datetime(work.get("ngay_kham"), errors="coerce", format="mixed")
    )
    work = work.sort_values("_visit_sort", kind="stable")
    rows: list[dict[str, Any]] = []
    for patient_key, history in work.groupby("patient_key", sort=True, dropna=False):
        latest = history.iloc[-1]
        facility_id = latest.get("facility_id")
        if _missing(facility_id):
            facility_id = None
        visit_dates = history["_visit_sort"].dropna()
        last_visit = latest["_visit_sort"]
        systolic = _measurement(latest.get("huyet_ap_tam_thu"))
        diastolic = _measurement(latest.get("huyet_ap_tam_truong"))
        glucose = _glucose(latest.get("chi_so_duong_huyet"))
        hba1c = _measurement(latest.get("chi_so_hba1c"))
        bp_controlled, bp_crisis, hba1c_controlled, out_of_control = _latest_flags(
            systolic, diastolic, hba1c
        )
        rows.append(
            {
                "patient_key": str(patient_key),
                "facility_id": facility_id,
                "ho_ten": _text(latest.get("ho_ten")),
                "sdt": _text(latest.get("sdt")),
                "dia_chi": _text(latest.get("dia_chi")),
                "last_visit_date": (
                    None if pd.isna(last_visit) else localize_local(last_visit)
                ),
                "last_systolic": systolic,
                "last_diastolic": diastolic,
                "last_glucose": glucose,
                "last_hba1c": hba1c,
                "is_bp_controlled": bp_controlled,
                "is_bp_crisis": bp_crisis,
                "is_hba1c_controlled": hba1c_controlled,
                "is_out_of_control": out_of_control,
                "has_contact": bool(_text(latest.get("sdt"))),
                "first_visit_date": (
                    localize_local(visit_dates.iloc[0]) if len(visit_dates) else None
                ),
                "visit_count": len(history),
                "uploaded_date": run_at,
            }
        )
    return rows
