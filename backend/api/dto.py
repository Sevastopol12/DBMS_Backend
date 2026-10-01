from datetime import datetime
from pathlib import PurePath
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, PlainSerializer

from backend.database.service.staging.schema import FileInfo
from backend.domain.processing.models import FileStatus
from backend.timezone import VIETNAM_TZ, VIETNAM_TZ_NAME

API_DISPLAY_TZ = VIETNAM_TZ_NAME
_API_DISPLAY_ZONE = VIETNAM_TZ


def _serialize_api_datetime(value: datetime) -> str:
    """Serialize metric timestamps in the API's display timezone."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=_API_DISPLAY_ZONE)
    return value.astimezone(_API_DISPLAY_ZONE).isoformat()


ApiDateTime = Annotated[
    datetime,
    PlainSerializer(
        _serialize_api_datetime,
        return_type=str,
        when_used="json",
    ),
]


class IssueCodeCount(BaseModel):
    code: str
    count: int


class PeriodSummaryMetric(BaseModel):
    facility_id: UUID
    period_grain: str
    period_start: ApiDateTime
    period_end: ApiDateTime
    visit_count: int
    unique_patient_count: int
    new_patient_count: int
    returning_patient_count: int
    repeat_visit_ratio: float | None = Field(default=None, allow_inf_nan=False)
    pct_tha: float | None = Field(default=None, allow_inf_nan=False)
    pct_dtd: float | None = Field(default=None, allow_inf_nan=False)
    pct_comorbid: float | None = Field(default=None, allow_inf_nan=False)
    bp_control_rate: float | None = Field(default=None, allow_inf_nan=False)
    bp_stage_normal_count: int
    bp_stage_1_count: int
    bp_stage_2_count: int
    bp_stage_crisis_count: int
    glycemic_control_rate: float | None = Field(default=None, allow_inf_nan=False)
    avg_glucose: float | None = Field(default=None, allow_inf_nan=False)
    median_glucose: float | None = Field(default=None, allow_inf_nan=False)
    avg_hba1c: float | None = Field(default=None, allow_inf_nan=False)
    median_hba1c: float | None = Field(default=None, allow_inf_nan=False)
    uploaded_date: ApiDateTime


class ComorbidityMetric(BaseModel):
    facility_id: UUID
    period_grain: str
    period_start: ApiDateTime
    diagnosis_label: str
    patient_count: int
    uploaded_date: ApiDateTime


class PatientStateMetric(BaseModel):
    patient_key: str
    facility_id: UUID
    ho_ten: str | None
    sdt: str | None
    dia_chi: str | None
    last_visit_date: ApiDateTime | None
    last_systolic: float | None = Field(default=None, allow_inf_nan=False)
    last_diastolic: float | None = Field(default=None, allow_inf_nan=False)
    last_glucose: float | None = Field(default=None, allow_inf_nan=False)
    last_hba1c: float | None = Field(default=None, allow_inf_nan=False)
    is_bp_controlled: bool | None
    is_bp_crisis: bool | None
    is_hba1c_controlled: bool | None
    is_out_of_control: bool | None
    has_contact: bool
    first_visit_date: ApiDateTime | None
    visit_count: int
    uploaded_date: ApiDateTime


class DataQualityMetric(BaseModel):
    facility_id: UUID
    period_grain: str
    period_start: ApiDateTime
    period_end: ApiDateTime
    files_processed: int
    avg_coverage_ratio: float | None = Field(default=None, allow_inf_nan=False)
    total_rows_seen: int
    accepted_rows: int
    flagged_rows: int
    rejected_rows: int
    top_issue_codes: list[IssueCodeCount]
    uploaded_date: ApiDateTime


class MetricsStatus(BaseModel):
    last_computed_at: ApiDateTime | None = None


class IngestionCreate(BaseModel):
    facility_id: UUID
    filename: str
    content: str | None = None
    content_type: str


class IngestionComplete(BaseModel):
    id: UUID
    facility_id: UUID
    content_hash: str
    size_bytes: int | None = None
    mappings: dict[str, Any] | None = None


class IngestionResponse(BaseModel):
    id: UUID
    facility_id: UUID
    filename: str | None = None
    object_key: str
    status: FileStatus

    presigned_url: str | None = None

    error_code: str | None = None
    error_message: str | None = None
    accepted_row_count: int = 0
    rejected_row_count: int = 0

    created_at: ApiDateTime


class MetricsGrainQuery(BaseModel):
    grain: Literal["1D", "3D", "1W", "2W", "1M", "ALL"]
    facility_id: UUID = None


class MetricsFacilityQuery(BaseModel):
    facility_id: UUID = None


def _get_safe_filename(filename: str) -> str:
    name = PurePath(filename).name
    if not name or name in {".", ".."}:
        raise ValueError("A valid filename is required")
    return "".join(
        character if character.isalnum() or character in ".-_" else "_"
        for character in name
    )


def _serialize_ingestion(
    file: FileInfo, presigned_url: str | None = None
) -> IngestionResponse:
    return IngestionResponse(
        id=file.id,
        facility_id=file.facility_id,
        filename=file.filename,
        object_key=file.object_key,
        status=file.status,
        presigned_url=presigned_url,
        accepted_row_count=file.accepted_row_count,
        rejected_row_count=file.rejected_row_count,
        error_code=file.error_code,
        error_message=file.error_message,
        created_at=file.created_at,
    )


__all__ = [
    "API_DISPLAY_TZ",
    "ApiDateTime",
    "ComorbidityMetric",
    "DataQualityMetric",
    "IngestionCreate",
    "IngestionComplete",
    "IngestionResponse",
    "IssueCodeCount",
    "MetricsGrainQuery",
    "MetricsFacilityQuery",
    "MetricsStatus",
    "PatientStateMetric",
    "PeriodSummaryMetric",
    "_get_safe_filename",
    "_serialize_ingestion",
]
