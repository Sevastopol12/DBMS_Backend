from datetime import datetime
from pathlib import PurePath
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

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
    period_grain: Literal["3D", "2W", "3M", "6M", "TODAY", "ALL"]
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
    bp_stage_elevated_count: int
    bp_stage_1_count: int
    bp_stage_2_count: int
    bp_stage_severe_count: int
    glycemic_control_rate: float | None = Field(default=None, allow_inf_nan=False)
    avg_glucose: float | None = Field(default=None, allow_inf_nan=False)
    median_glucose: float | None = Field(default=None, allow_inf_nan=False)
    avg_hba1c: float | None = Field(default=None, allow_inf_nan=False)
    median_hba1c: float | None = Field(default=None, allow_inf_nan=False)
    computed_at: ApiDateTime


class ComorbidityMetric(BaseModel):
    facility_id: UUID
    period_grain: Literal["3D", "2W", "3M", "6M", "TODAY", "ALL"]
    period_start: ApiDateTime
    diagnosis_label: str
    patient_count: int
    computed_at: ApiDateTime


class PatientStateMetric(BaseModel):
    patient_key: str
    facility_id: UUID
    ho_ten: str | None
    sdt: str
    dia_chi: str | None
    last_visit_date: ApiDateTime | None
    last_systolic: float | None = Field(default=None, allow_inf_nan=False)
    last_diastolic: float | None = Field(default=None, allow_inf_nan=False)
    last_glucose: float | None = Field(default=None, allow_inf_nan=False)
    last_hba1c: float | None = Field(default=None, allow_inf_nan=False)
    is_bp_controlled: bool | None
    is_bp_severe: bool | None
    is_hba1c_controlled: bool | None
    is_out_of_control: bool | None
    has_contact: bool
    first_visit_date: ApiDateTime | None
    visit_count: int
    computed_at: ApiDateTime


class DataQualityMetric(BaseModel):
    facility_id: UUID
    period_grain: Literal["3D", "2W", "3M", "6M", "TODAY", "ALL"]
    period_start: ApiDateTime
    period_end: ApiDateTime
    files_processed: int
    avg_mapping_coverage_ratio: float | None = Field(default=None, allow_inf_nan=False)
    total_rows_seen: int
    accepted_rows: int
    rejected_rows: int
    ignored_duplicate_row_count: int
    top_issue_codes: list[IssueCodeCount]
    computed_at: ApiDateTime


class MetricsStatus(BaseModel):
    last_computed_at: ApiDateTime | None = None


class IngestionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    content_type: str


class IngestionComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    content_hash: str
    size_bytes: int | None = None
    mappings: dict[str, Any] | None = None


class UploadReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_file_id: UUID
    filename: str
    content_type: str


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
    ignored_duplicate_row_count: int = 0

    parent_file_id: UUID | None = None
    rejection_report_available: bool = False
    rejection_report_expires_at: ApiDateTime | None = None

    created_at: ApiDateTime


class FileDetailResponse(BaseModel):
    id: UUID
    facility_id: UUID
    filename: str | None = None
    object_key: str | None = None
    status: FileStatus
    error_code: str | None = None
    error_message: str | None = None
    accepted_row_count: int = 0
    rejected_row_count: int = 0
    ignored_duplicate_row_count: int = 0
    parent_file_id: UUID | None = None
    rejection_report_available: bool = False
    rejection_report_expires_at: ApiDateTime | None = None
    created_at: ApiDateTime | None = None
    uploaded_at: ApiDateTime | None = None
    completed_at: ApiDateTime | None = None


class RejectionDownloadResponse(BaseModel):
    url: str
    expires_in_seconds: int
    filename: str


class RejectedArtifactItem(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    file_id: UUID
    parent_file_id: UUID | None = None
    file_status: str
    state: Literal["available", "expired"]
    artifact_created_at: ApiDateTime | None = None
    artifact_expires_at: ApiDateTime | None = None
    rejected_row_count: int = 0


class RejectedArtifactListResponse(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    items: list[RejectedArtifactItem]
    next_cursor: str | None = None
    limit: int


class RejectedArtifactDownload(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    file_id: UUID
    download_url: str
    artifact_filename: str
    url_expires_at: ApiDateTime


class MetricsGrainQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grain: Literal["3D", "2W", "3M", "6M", "TODAY", "ALL"]


class MetricsFacilityQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    artifact_key = getattr(file, "rejection_artifact_key", None)
    artifact_expires = getattr(file, "rejection_artifact_expires_at", None)
    return IngestionResponse(
        id=file.id,
        facility_id=file.facility_id,
        filename=file.filename,
        object_key=file.object_key,
        status=file.status,
        presigned_url=presigned_url,
        accepted_row_count=file.accepted_row_count or 0,
        rejected_row_count=file.rejected_row_count or 0,
        ignored_duplicate_row_count=getattr(file, "ignored_duplicate_row_count", 0)
        or 0,
        parent_file_id=getattr(file, "parent_file_id", None),
        rejection_report_available=artifact_key is not None,
        rejection_report_expires_at=artifact_expires,
        error_code=file.error_code,
        error_message=file.error_message,
        created_at=file.created_at,
    )


def _serialize_file_detail(file: FileInfo) -> FileDetailResponse:
    artifact_key = getattr(file, "rejection_artifact_key", None)
    artifact_expires = getattr(file, "rejection_artifact_expires_at", None)
    return FileDetailResponse(
        id=file.id,
        facility_id=file.facility_id,
        filename=file.filename,
        object_key=file.object_key,
        status=file.status,
        error_code=file.error_code,
        error_message=file.error_message,
        accepted_row_count=file.accepted_row_count or 0,
        rejected_row_count=file.rejected_row_count or 0,
        ignored_duplicate_row_count=getattr(file, "ignored_duplicate_row_count", 0)
        or 0,
        parent_file_id=getattr(file, "parent_file_id", None),
        rejection_report_available=artifact_key is not None,
        rejection_report_expires_at=artifact_expires,
        created_at=file.created_at,
        uploaded_at=getattr(file, "uploaded_at", None),
        completed_at=getattr(file, "completed_at", None),
    )


__all__ = [
    "API_DISPLAY_TZ",
    "ApiDateTime",
    "ComorbidityMetric",
    "DataQualityMetric",
    "FileDetailResponse",
    "IngestionComplete",
    "IngestionCreate",
    "IngestionResponse",
    "IssueCodeCount",
    "MetricsFacilityQuery",
    "MetricsGrainQuery",
    "MetricsStatus",
    "PatientStateMetric",
    "PeriodSummaryMetric",
    "RejectedArtifactDownload",
    "RejectedArtifactItem",
    "RejectedArtifactListResponse",
    "RejectionDownloadResponse",
    "UploadReportCreate",
    "_get_safe_filename",
    "_serialize_file_detail",
    "_serialize_ingestion",
]
