from pydantic import BaseModel


class FileRecord(BaseModel):
    filename: str
    hashed_value: str
    mapping: dict[str, str]


class FileRegister(BaseModel):
    filename: str
    content_type: str


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


class ResponseURL(BaseModel):
    presigned_url: str


class RecordedResult(BaseModel):
    filename: str
    location: str
    created_at: str


__all__ = ["Report", "FileRegister", "FileRecord", "ResponseURL", "RecordedResult"]
