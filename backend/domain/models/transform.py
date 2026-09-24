from datetime import date, datetime
from enum import Enum
from pydantic import BaseModel, Field, field_validator
import uuid
from uuid import UUID
from typing import TypeAlias


SourceCellValue: TypeAlias = object | None
SourceRow: TypeAlias = dict[str, SourceCellValue]


class ReportRow(BaseModel):
    ma_bhyt: str | None = None
    cccd: str | None = None
    facility_id: uuid.UUID | None = None

    # Demographic
    ho_ten: str | None = None
    gioi_tinh: str | None = None
    nam_sinh: str | None = None
    sdt: str | None = None

    # Address
    dia_chi: str | None = None

    ngay_kham: datetime | None = None

    # Clinical metrics

    # Icd hypertension
    icd_tha: str | None = None
    # Icd diabetes
    icd_dtd: str | None = None
    chan_doan_di_kem: str | None = None
    # Diastolic blood pressure
    huyet_ap_tam_truong: str | None = None
    # Systolic blood pressure
    huyet_ap_tam_thu: str | None = None

    chi_so_duong_huyet: str | None = None
    chi_so_hba1c: str | None = None

    ghi_chu: str | None = None
    dieu_tri: str | None = None

    @field_validator("ngay_kham", mode="before")
    @classmethod
    def parse_visit_date(cls, value: object) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            for parser in (datetime.fromisoformat,):
                try:
                    return parser(text)
                except ValueError:
                    continue
        raise ValueError("ngay_kham must be an ISO date or datetime")


class ColumnMap(BaseModel):
    original_name: str
    normalized_name: str
    mapping_target: str | None


class CacheSource(str, Enum):
    DIRECT = "DIRECT"
    DYNAMIC = "DYNAMIC"


class HeaderMapValue(BaseModel):
    value: str | None
    cache_key: CacheSource


class SourceDataset(BaseModel):
    """Raw tabular data with rows keyed by the original header names."""

    source_file_id: UUID
    filename: str
    headers: list[str]
    rows: list[SourceRow] = Field(default_factory=list)


__all__ = [
    "SourceRow",
    "ReportRow",
    "ColumnMap",
    "CacheSource",
    "HeaderMapValue",
    "SourceDataset",
    "SourceCellValue",
]
