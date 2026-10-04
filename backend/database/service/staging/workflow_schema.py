from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.base import Base


class WorkflowType(str, Enum):
    TRANSFORM_SWEEP = "TRANSFORM_SWEEP"
    TRANSFORM_MANUAL = "TRANSFORM_MANUAL"
    COMPUTATION = "COMPUTATION"


class TriggerType(str, Enum):
    SCHEDULED = "SCHEDULED"
    MANUAL = "MANUAL"


class WorkflowStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


_WORKFLOW_TYPE_VALUES = "('TRANSFORM_SWEEP','TRANSFORM_MANUAL','COMPUTATION')"
_TRIGGER_TYPE_VALUES = "('SCHEDULED','MANUAL')"
_STATUS_VALUES = "('RUNNING','SUCCEEDED','PARTIAL','FAILED','SKIPPED')"


class WorkflowRunLog(Base):
    __tablename__ = "workflow_run_log"
    __table_args__ = (
        CheckConstraint(
            f"workflow_type IN {_WORKFLOW_TYPE_VALUES}",
            name="workflow_run_log_workflow_type_check",
        ),
        CheckConstraint(
            f"trigger_type IN {_TRIGGER_TYPE_VALUES}",
            name="workflow_run_log_trigger_type_check",
        ),
        CheckConstraint(
            f"status IN {_STATUS_VALUES}",
            name="workflow_run_log_status_check",
        ),
        Index(
            "workflow_run_log_type_started_idx",
            "workflow_type",
            text("started_at DESC"),
        ),
        {"schema": "Files"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    workflow_type: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    items_seen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    items_dispatched: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    items_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    items_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    celery_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    computation_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )


__all__ = [
    "TriggerType",
    "WorkflowRunLog",
    "WorkflowStatus",
    "WorkflowType",
]
