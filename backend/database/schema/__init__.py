from sqlalchemy import Text, DateTime, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from uuid import UUID
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.domain.models import FileStatus


class Base(DeclarativeBase):
    pass


class SystemReport(Base):
    __tablename__ = "report"
    __table_args__ = (
        UniqueConstraint("source_file_id", "row_index", name="source_unique"),
        {"schema": "Diabetes"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    source_file_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    row_index: Mapped[str] = mapped_column(Text, nullable=False)
    source_size_bytes: Mapped[int] = mapped_column(Integer, nullable=True)

    ma_bhyt: Mapped[str] = mapped_column(Text, nullable=True)
    cccd: Mapped[str] = mapped_column(Text, nullable=True)

    ho_ten: Mapped[str | None] = mapped_column(Text, nullable=True)
    gioi_tinh: Mapped[str | None] = mapped_column(Text, nullable=True)
    nam_sinh: Mapped[str | None] = mapped_column(Text, nullable=True)
    sdt: Mapped[str | None] = mapped_column(Text, nullable=True)

    dia_chi: Mapped[str | None] = mapped_column(Text, nullable=True)
    phuong_xa: Mapped[str | None] = mapped_column(Text, nullable=True)
    quan_huyen: Mapped[str | None] = mapped_column(Text, nullable=True)
    tinh_thanh_pho: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    # The digest is only known after upload completion.
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mappings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

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


class FileErrorRecord(Base):
    __tablename__ = "ingestion_errors"
    __table_args__ = (
        UniqueConstraint(
            "file_id",
            "row_number",
            "column",
            "target_field",
            "issue_code",
            name="ingestion_error_lineage_unique",
        ),
        {"schema": "Files"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    column: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_column: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_field: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    issue_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")),
    )


__all__ = ["SystemReport", "FileInfo", "Base", "FileErrorRecord"]
