from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.base import Base

_PERIOD_GRAIN_CHECK = "period_grain IN ('1D','3D','1W','2W','1M','ALL')"


class MetricPeriodSummary(Base):
    __tablename__ = "metric_period_summary"
    __table_args__ = (
        CheckConstraint(_PERIOD_GRAIN_CHECK),
        UniqueConstraint(
            "run_id",
            "facility_id",
            "period_grain",
            "period_start",
            name="metric_period_summary_unique",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "Metrics"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("Metrics.computation_run_log.run_id"),
        nullable=False,
    )
    facility_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    period_grain: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    visit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    unique_patient_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    new_patient_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    returning_patient_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    repeat_visit_ratio: Mapped[float | None] = mapped_column(
        DOUBLE_PRECISION, nullable=True
    )
    pct_tha: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    pct_dtd: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    pct_comorbid: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    bp_control_rate: Mapped[float | None] = mapped_column(
        DOUBLE_PRECISION, nullable=True
    )
    bp_stage_normal_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    bp_stage_1_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    bp_stage_2_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    bp_stage_crisis_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    glycemic_control_rate: Mapped[float | None] = mapped_column(
        DOUBLE_PRECISION, nullable=True
    )
    avg_glucose: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    median_glucose: Mapped[float | None] = mapped_column(
        DOUBLE_PRECISION, nullable=True
    )
    avg_hba1c: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    median_hba1c: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    uploaded_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MetricComorbidityBreakdown(Base):
    __tablename__ = "metric_comorbidity_breakdown"
    __table_args__ = (
        CheckConstraint(_PERIOD_GRAIN_CHECK),
        UniqueConstraint(
            "run_id",
            "facility_id",
            "period_grain",
            "period_start",
            "diagnosis_label",
            name="metric_comorbidity_breakdown_unique",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "Metrics"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("Metrics.computation_run_log.run_id"),
        nullable=False,
    )
    facility_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    period_grain: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    diagnosis_label: Mapped[str] = mapped_column(Text, nullable=False)
    patient_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    uploaded_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class PatientCurrentState(Base):
    __tablename__ = "patient_current_state"
    __table_args__ = ({"schema": "Metrics"},)

    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("Metrics.computation_run_log.run_id"),
        primary_key=True,
    )
    patient_key: Mapped[str] = mapped_column(Text, primary_key=True)
    facility_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    ho_ten: Mapped[str | None] = mapped_column(Text, nullable=True)
    sdt: Mapped[str | None] = mapped_column(Text, nullable=True)
    dia_chi: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_visit_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_systolic: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    last_diastolic: Mapped[float | None] = mapped_column(
        DOUBLE_PRECISION, nullable=True
    )
    last_glucose: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    last_hba1c: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    is_bp_controlled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_bp_crisis: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_hba1c_controlled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_out_of_control: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    first_visit_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    visit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    uploaded_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MetricDataQualitySummary(Base):
    __tablename__ = "metric_data_quality_summary"
    __table_args__ = (
        CheckConstraint(_PERIOD_GRAIN_CHECK),
        UniqueConstraint(
            "run_id",
            "facility_id",
            "period_grain",
            "period_start",
            name="metric_data_quality_summary_unique",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "Metrics"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("Metrics.computation_run_log.run_id"),
        nullable=False,
    )
    facility_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    period_grain: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    files_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    avg_coverage_ratio: Mapped[float | None] = mapped_column(
        DOUBLE_PRECISION, nullable=True
    )
    total_rows_seen: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    accepted_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    flagged_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    rejected_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    top_issue_codes: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    uploaded_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ComputationRunLog(Base):
    __tablename__ = "computation_run_log"
    __table_args__ = (
        CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED')"),
        {"schema": "Metrics"},
    )

    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    rows_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pruned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # The partial single-RUNNING index is declared by migration 007, not ORM.


__all__ = [
    "ComputationRunLog",
    "MetricComorbidityBreakdown",
    "MetricDataQualitySummary",
    "MetricPeriodSummary",
    "PatientCurrentState",
]
