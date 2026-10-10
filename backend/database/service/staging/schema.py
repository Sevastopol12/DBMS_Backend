from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.base import Base
from backend.domain.processing.models import FileStatus
from backend.timezone import now_vietnam


class FileInfo(Base):
    __tablename__ = "ingestion_files"
    __table_args__ = (
        UniqueConstraint(
            "facility_id",
            "content_hash",
            name="ingestion_files_facility_hash_unique",
        ),
        Index("ingestion_files_status_idx", "status"),
        Index(
            "ingestion_files_facility_created_idx",
            "facility_id",
            text("created_at DESC"),
        ),
        {"schema": "Files"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, nullable=False
    )
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    facility_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=FileStatus.CREATED
    )

    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mappings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    quality_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=now_vietnam,
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

    # WP-06 lineage/artifact columns (migration 011)
    parent_file_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    ignored_duplicate_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    rejection_artifact_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_artifact_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Migration 014: artifact lifecycle timestamps (no backfill).
    # artifact_created_at records when the rejection object was written;
    # artifact_purged_at records when the purge task deleted the object.
    # The key/expires columns are retained after purge for audit.
    artifact_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    artifact_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Wave 1A additions (CONTRACTS §3)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = ["FileInfo"]
