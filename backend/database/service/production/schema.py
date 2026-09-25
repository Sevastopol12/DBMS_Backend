from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.base import Base
from backend.database.canonical import CANONICAL_FIELD_SET


class SystemReport(Base):
    __tablename__ = "report"
    __table_args__ = (
        UniqueConstraint(
            "source_file_id", "source_row_number", name="source_row_unique"
        ),
        {"schema": "Diabetes"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    source_file_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)

    ma_bhyt: Mapped[str] = mapped_column(Text, nullable=True)
    cccd: Mapped[str] = mapped_column(Text, nullable=True)
    facility_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    ho_ten: Mapped[str | None] = mapped_column(Text, nullable=True)
    gioi_tinh: Mapped[str | None] = mapped_column(Text, nullable=True)
    nam_sinh: Mapped[str | None] = mapped_column(Text, nullable=True)
    sdt: Mapped[str | None] = mapped_column(Text, nullable=True)

    dia_chi: Mapped[str | None] = mapped_column(Text, nullable=True)
    ngay_kham: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    icd_tha: Mapped[str | None] = mapped_column(Text, nullable=True)
    icd_dtd: Mapped[str | None] = mapped_column(Text, nullable=True)
    chan_doan_di_kem: Mapped[str | None] = mapped_column(Text, nullable=True)

    huyet_ap_tam_truong: Mapped[str | None] = mapped_column(Text, nullable=True)
    huyet_ap_tam_thu: Mapped[str | None] = mapped_column(Text, nullable=True)

    chi_so_duong_huyet: Mapped[str | None] = mapped_column(Text, nullable=True)
    chi_so_hba1c: Mapped[str | None] = mapped_column(Text, nullable=True)

    ghi_chu: Mapped[str | None] = mapped_column(Text, nullable=True)
    dieu_tri: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReviewRecord(Base):
    __tablename__ = "report_review"
    __table_args__ = (
        UniqueConstraint(
            "source_file_id", "source_row_number", name="review_row_unique"
        ),
        {"schema": "Diabetes"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_file_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    disposition: Mapped[str] = mapped_column(Text, nullable=False)
    issue_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )


_SYSTEM_REPORT_METADATA_FIELDS = {
    "id",
    "source_file_id",
    "source_size_bytes",
    "source_row_number",
    "facility_id",
}
_SYSTEM_REPORT_CANONICAL_FIELDS = {
    column.name
    for column in SystemReport.__table__.columns
    if column.name not in _SYSTEM_REPORT_METADATA_FIELDS
}
if _SYSTEM_REPORT_CANONICAL_FIELDS != CANONICAL_FIELD_SET:
    raise RuntimeError(
        "SystemReport canonical columns drifted from CANONICAL_FIELDS: "
        f"missing={sorted(CANONICAL_FIELD_SET - _SYSTEM_REPORT_CANONICAL_FIELDS)}, "
        f"extra={sorted(_SYSTEM_REPORT_CANONICAL_FIELDS - CANONICAL_FIELD_SET)}"
    )


__all__ = ["ReviewRecord", "SystemReport"]
