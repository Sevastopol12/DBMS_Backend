from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class Report(BaseModel):
    ma_bhyt: str
    cccd: str

    ho_ten: str | None = None
    gioi_tinh: str | None = None
    nam_sinh: str | None = None
    sdt: str | None = None

    dia_chi: str | None = None
    phuong_xa: str | None = None
    quan_huyen: str | None = None
    tinh_thanh_pho: str | None = None

    ngay_kham: str | None = None

    icd_tha: str | None = None
    icd_dtd: str | None = None
    huyet_ap_tam_truong: str | None = None
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
    object_key: str
    status: str

    presigned_url: str | None = None

    error_code: str | None = None
    error_message: str | None = None
    accepted_row_count: int = 0
    rejected_row_count: int = 0

    created_at: datetime


__all__ = ["Report", "IngestionResponse", "IngestionCreate", "IngestionComplete"]
