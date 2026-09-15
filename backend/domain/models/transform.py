from pydantic import BaseModel
from uuid import UUID
from typing import Any


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
    phuong_xa: str | None = None
    quan_huyen: str | None = None
    tinh_thanh_pho: str | None = None

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


class TransformResult(BaseModel):
    file_id: UUID
    accepted_row_count: int
    rejected_row_count: int


class ErrorLog(BaseModel):
    row_number: int
    status: str
    normalized: dict[str, Any]
    issues: dict[str, Any]
