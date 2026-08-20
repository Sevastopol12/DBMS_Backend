from pydantic import BaseModel


class ReportCreate(BaseModel):
    ma_bhyt: str
    cccd: str
    ma_bn: str

    ho_ten: str | None = None
    gioi_tinh: str | None = None
    nam_sinh: str | None = None
    dia_chi: str | None = None
    ngay_kham: str | None = None

    icd_tha: str | None = None
    icd_dtd: str | None = None

    huyet_ap_tam_truong: str | None = None
    huyet_ap_tam_thu: str | None = None
    chi_so_duong_huyet: str | None = None
    chi_so_khac: str | None = None

    ghi_chu: str | None = None
    dieu_tri: str | None = None


__all__ = ["Report"]
