from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Text,
    DateTime,
    Integer,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from uuid import UUID
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.domain.models import FileStatus
from backend.domain.models.canonical import CANONICAL_FIELD_SET


class Base(DeclarativeBase):
    pass


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


class FileInfo(Base):
    __tablename__ = "ingestion_files"
    __table_args__ = (
        UniqueConstraint("content_hash", name="ingestion_files_content_hash_unique"),
        {"schema": "Files"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, nullable=False
    )
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(default=FileStatus.CREATED)

    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mappings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    quality_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    facility_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")),
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class HeaderMapping(Base):
    __tablename__ = "header_mapping"
    __table_args__ = (
        CheckConstraint(
            "btrim(normalized_alias) <> ''",
            name="header_mapping_normalized_alias_nonblank",
        ),
        CheckConstraint(
            "tier IN ('DIRECT', 'DYNAMIC')",
            name="header_mapping_tier_valid",
        ),
        CheckConstraint(
            "btrim(target) <> ''",
            name="header_mapping_target_nonblank",
        ),
        {"schema": "Mapping"},
    )

    normalized_alias: Mapped[str] = mapped_column(Text, primary_key=True)
    tier: Mapped[str] = mapped_column(Text, primary_key=True)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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


__all__ = [
    "SystemReport",
    "ReviewRecord",
    "FileInfo",
    "HeaderMapping",
    "Base",
]
