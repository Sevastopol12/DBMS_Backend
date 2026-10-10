from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class PeriodGrain(str, Enum):
    THREE_DAYS = "3D"
    TWO_WEEKS = "2W"
    THREE_MONTHS = "3M"
    SIX_MONTHS = "6M"
    TODAY = "TODAY"
    ALL = "ALL"


class PeriodSummaryRow(BaseModel):
    facility_id: UUID
    period_grain: str
    period_start: datetime
    period_end: datetime
    visit_count: int
    unique_patient_count: int
    new_patient_count: int
    returning_patient_count: int
    repeat_visit_ratio: float | None
    pct_tha: float | None
    pct_dtd: float | None
    pct_comorbid: float | None
    bp_control_rate: float | None
    bp_stage_normal_count: int
    bp_stage_elevated_count: int
    bp_stage_1_count: int
    bp_stage_2_count: int
    bp_stage_severe_count: int
    glycemic_control_rate: float | None
    avg_glucose: float | None
    median_glucose: float | None
    avg_hba1c: float | None
    median_hba1c: float | None
    computed_at: datetime


class ComorbidityRow(BaseModel):
    facility_id: UUID
    period_grain: str
    period_start: datetime
    diagnosis_label: str
    patient_count: int
    computed_at: datetime


class PatientStateRow(BaseModel):
    patient_key: str
    facility_id: UUID
    ho_ten: str | None
    sdt: str | None
    dia_chi: str | None
    last_visit_date: datetime | None
    last_systolic: float | None
    last_diastolic: float | None
    last_glucose: float | None
    last_hba1c: float | None
    is_bp_controlled: bool | None
    is_bp_severe: bool | None
    is_hba1c_controlled: bool | None
    is_out_of_control: bool | None
    has_contact: bool
    first_visit_date: datetime | None
    visit_count: int
    computed_at: datetime


class DataQualityRow(BaseModel):
    facility_id: UUID
    period_grain: str
    period_start: datetime
    period_end: datetime
    files_processed: int
    avg_mapping_coverage_ratio: float | None
    total_rows_seen: int
    accepted_rows: int
    rejected_rows: int
    ignored_duplicate_row_count: int
    top_issue_codes: list[dict[str, Any]]
    computed_at: datetime
