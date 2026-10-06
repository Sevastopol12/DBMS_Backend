from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.base import Base
from backend.database.canonical import (
    CANONICAL_FIELD_SET,
    FIELD_BY_NAME,
    IDENTITY_FIELDS,
)


class Demographic(Base):
    __tablename__ = "Demographic"
    __table_args__ = (
        UniqueConstraint(
            "facility_id", "cccd", "ngay_kham", name="demographic_visit_unique"
        ),
        CheckConstraint("cccd ~ '^[0-9]{12}$'", name="demographic_cccd_format"),
        CheckConstraint(
            "date_trunc('second', ngay_kham) = ngay_kham",
            name="demographic_whole_second",
        ),
        {"schema": "Diabetes"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    facility_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    cccd: Mapped[str] = mapped_column(Text, nullable=False)
    ngay_kham: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_file_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_file_uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    ma_bhyt: Mapped[str | None] = mapped_column(Text, nullable=True)
    ho_ten: Mapped[str] = mapped_column(Text, nullable=False)
    gioi_tinh: Mapped[str | None] = mapped_column(Text, nullable=True)
    nam_sinh: Mapped[str] = mapped_column(Text, nullable=False)
    sdt: Mapped[str] = mapped_column(Text, nullable=False)
    dia_chi: Mapped[str | None] = mapped_column(Text, nullable=True)
    ghi_chu: Mapped[str | None] = mapped_column(Text, nullable=True)
    dieu_tri: Mapped[str | None] = mapped_column(Text, nullable=True)


class Measurement(Base):
    __tablename__ = "Measurement"
    __table_args__ = (
        UniqueConstraint(
            "facility_id", "cccd", "ngay_kham", name="measurement_visit_unique"
        ),
        ForeignKeyConstraint(
            ["facility_id", "cccd", "ngay_kham"],
            [
                "Diabetes.Demographic.facility_id",
                "Diabetes.Demographic.cccd",
                "Diabetes.Demographic.ngay_kham",
            ],
            name="measurement_demographic_fk",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        CheckConstraint(
            "date_trunc('second', ngay_kham) = ngay_kham",
            name="measurement_whole_second",
        ),
        {"schema": "Diabetes"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    facility_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    cccd: Mapped[str] = mapped_column(Text, nullable=False)
    ngay_kham: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_file_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_file_uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    icd_tha: Mapped[str] = mapped_column(Text, nullable=False)
    icd_dtd: Mapped[str] = mapped_column(Text, nullable=False)
    chan_doan_di_kem: Mapped[str | None] = mapped_column(Text, nullable=True)
    huyet_ap_tam_truong: Mapped[str] = mapped_column(Text, nullable=False)
    huyet_ap_tam_thu: Mapped[str] = mapped_column(Text, nullable=False)
    chi_so_duong_huyet: Mapped[str] = mapped_column(Text, nullable=False)
    chi_so_hba1c: Mapped[str] = mapped_column(Text, nullable=False)


class ReviewRecord(Base):
    __tablename__ = "report_review"
    __table_args__ = (
        UniqueConstraint(
            "source_file_id", "source_row_number", name="review_row_unique"
        ),
        CheckConstraint(
            "source_row_number >= 2", name="report_review_source_row_number_check"
        ),
        CheckConstraint(
            "disposition IN ('ACCEPTED','REJECTED')",
            name="report_review_disposition_check",
        ),
        CheckConstraint(
            "duplicate_role IN ('NONE','PRIMARY','MERGED')",
            name="report_review_duplicate_role_check",
        ),
        CheckConstraint(
            "disposition <> 'ACCEPTED' OR duplicate_role = 'MERGED'",
            name="review_accepted_only_merged",
        ),
        CheckConstraint(
            "(duplicate_role = 'MERGED') = (merged_into_row IS NOT NULL)",
            name="review_merged_has_target",
        ),
        {"schema": "Diabetes"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_file_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    disposition: Mapped[str] = mapped_column(Text, nullable=False)
    duplicate_role: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="NONE"
    )
    merged_into_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_row_numbers: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    issue_codes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


_METADATA_FIELDS = {
    "id",
    "facility_id",
    "source_file_id",
    "source_file_uploaded_at",
    "uploaded_at",
}
_DEMOGRAPHIC_COLUMNS = {column.name for column in Demographic.__table__.columns}
_MEASUREMENT_COLUMNS = {column.name for column in Measurement.__table__.columns}
_SHARED_IDENTITY = set(IDENTITY_FIELDS)
_CANONICAL_COLUMNS = (_DEMOGRAPHIC_COLUMNS | _MEASUREMENT_COLUMNS) - _METADATA_FIELDS
if _CANONICAL_COLUMNS != CANONICAL_FIELD_SET:
    raise RuntimeError(
        "Accepted-data canonical columns drifted: "
        f"missing={sorted(CANONICAL_FIELD_SET - _CANONICAL_COLUMNS)}, "
        f"extra={sorted(_CANONICAL_COLUMNS - CANONICAL_FIELD_SET)}"
    )
for _model in (Demographic, Measurement):
    _columns = {column.name: column for column in _model.__table__.columns}
    for _field in CANONICAL_FIELD_SET.intersection(_columns):
        _expected_nullable = not FIELD_BY_NAME[_field].required
        if _columns[_field].nullable != _expected_nullable:
            raise RuntimeError(
                f"{_model.__name__}.{_field} nullable drift: "
                f"expected={_expected_nullable}, actual={_columns[_field].nullable}"
            )
    _missing_identity = _SHARED_IDENTITY - _columns.keys()
    if _missing_identity:
        raise RuntimeError(
            f"{_model.__name__} missing identity fields: {sorted(_missing_identity)}"
        )


def _field_map(model: type[Any]) -> frozenset[str]:
    return frozenset(
        column.name
        for column in model.__table__.columns
        if column.name not in _METADATA_FIELDS | {"id"}
    )


DEMOGRAPHIC_FIELDS = _field_map(Demographic)
MEASUREMENT_FIELDS = _field_map(Measurement)

__all__ = [
    "DEMOGRAPHIC_FIELDS",
    "MEASUREMENT_FIELDS",
    "Demographic",
    "Measurement",
    "ReviewRecord",
]
