from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Any

from backend.database.schema import FileStatus


class TaskReport(BaseModel):
    report_rows: list[dict[str, Any]]
    logs: list[str]
    accepted_row: int
    rejected_row: int


class ReportRow(BaseModel):
    ma_bhyt: str | None = None
    cccd: str | None = None

    ho_ten: str | None = None
    gioi_tinh: str | None = None
    nam_sinh: str | None = None
    sdt: str | None = None

    # Address
    dia_chi: str | None = None
    phuong_xa: str | None = None
    quan_huyen: str | None = None
    tinh_thanh_pho: str | None = None

    ngay_kham: str | None = None

    # clinical metrics

    # icd hypertension
    icd_tha: str | None = None
    # icd diabetes
    icd_dtd: str | None = None
    # Diastolic blood pressure
    huyet_ap_tam_truong: str | None = None
    # Systolic blood pressure
    huyet_ap_tam_thu: str | None = None
    chi_so_duong_huyet: str | None = None
    chi_so_hba1c: str | None = None

    ghi_chu: str | None = None
    dieu_tri: str | None = None


class IngestionCreate(BaseModel):
    filename: str
    content: str | None = None
    content_type: str


class IngestionComplete(BaseModel):
    id: UUID
    content_hash: str
    size_bytes: int | None = None
    mappings: dict[str, str] | None = None


class IngestionResponse(BaseModel):
    id: UUID
    filename: str | None = None
    object_key: str
    status: FileStatus

    presigned_url: str | None = None

    error_code: str | None = None
    error_message: str | None = None
    accepted_row_count: int = 0
    rejected_row_count: int = 0

    created_at: datetime


class TransformResult(BaseModel):
    file_id: UUID
    accepted_row_count: int
    rejected_row_count: int


class ErrorLog(BaseModel):
    row_number: int
    status: str
    normalized: dict[str, Any]
    issues: dict[str, Any]


class MappingRequest(BaseModel):
    filename: str
    columns: list[str]


class MappingResponse(BaseModel):
    filename: str
    mapping: dict[str, str | None] | None = None


__all__ = [
    "ReportRow",
    "IngestionResponse",
    "IngestionCreate",
    "IngestionComplete",
    "MappingRequest",
    "MappingResponse",
]
