from pydantic import BaseModel, Field
from uuid import UUID
from typing import Any, TypeAlias


SourceCellValue: TypeAlias = object | None
SourceRow: TypeAlias = dict[str, SourceCellValue]


class TaskReport(BaseModel):
    report_rows: list[dict[str, Any]]
    logs: list[str]
    accepted_row: int
    rejected_row: int


class ReportRow(BaseModel):
    ma_bhyt: str | None = None
    cccd: str | None = None

    # Demographic
    ho_ten: str | None = None
    gioi_tinh: str | None = None
    nam_sinh: str | None = None
    sdt: str | None = None

    # Address
    dia_chi: str | None = None

    ngay_kham: str | None = None

    # Clinical metrics

    # Icd hypertension
    icd_tha: str | None = None
    # Icd diabetes
    icd_dtd: str | None = None
    # Diastolic blood pressure
    huyet_ap_tam_truong: str | None = None
    # Systolic blood pressure
    huyet_ap_tam_thu: str | None = None

    chi_so_duong_huyet: str | None = None
    chi_so_hba1c: str | None = None

    ghi_chu: str | None = None
    dieu_tri: str | None = None


class ColumnMap(BaseModel):
    original_name: str
    normalized_name: str
    mapping_target: str | None


class SourceDataset(BaseModel):
    """Raw tabular data with rows keyed by the original header names."""

    source_file_id: UUID
    filename: str
    headers: list[str]
    rows: list[SourceRow] = Field(default_factory=list)


class TransformResult(BaseModel):
    file_id: UUID

    accepted_row_count: int
    rejected_row_count: int


class ErrorLog(BaseModel):
    row_number: int
    status: str
    normalized: dict[str, Any]
    issues: dict[str, Any]
