from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, model_validator

from backend.api.dto import ApiDateTime

OpsStatus = Literal["QUEUED", "ERROR", "SUCCEED", "REJECTED"]


class TransformRequest(BaseModel):
    file_ids: list[UUID] | None = None
    statuses: list[OpsStatus] | None = None
    force: bool = False

    @model_validator(mode="after")
    def validate_selector(self) -> TransformRequest:
        if not self.file_ids and not self.statuses:
            raise ValueError("file_ids or statuses is required")
        return self


class ComputeRequest(BaseModel):
    force: bool = False


class TransformResponse(BaseModel):
    run_id: UUID
    selected: int
    requeued: int
    already_queued: int
    dispatched: int
    dispatch_failed: int
    skipped_total: int
    skipped_by_reason: dict[str, int]
    skipped: list[dict[str, str]]


class ComputeResponse(BaseModel):
    task_id: str


class HealthWorkflow(BaseModel):
    last_run: dict | None
    expected_interval_seconds: int
    overdue: bool | None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, bool]
    workflows: dict[str, HealthWorkflow]


class FileSummaryResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    errors: dict
    rejected_by_code: dict[str, int]
    oldest_queued_at: ApiDateTime | None
    oldest_queued_age_seconds: float | None
    last_completed_at: ApiDateTime | None


class FileListResponse(BaseModel):
    items: list[dict]
    limit: int
    offset: int


class FileDetailResponse(BaseModel):
    production: dict[str, int]
    # The repository's keys are intentionally preserved for operational clients.
    model_config = {"extra": "allow"}


class RunListResponse(BaseModel):
    items: list[dict]


class ScheduleEntry(BaseModel):
    name: str
    task: str
    interval_seconds: float | None
    last_run_at: ApiDateTime | None
    total_run_count: int


class ScheduleResponse(BaseModel):
    available: bool
    entries: list[ScheduleEntry]


__all__ = [
    "ComputeRequest", "ComputeResponse", "FileDetailResponse",
    "FileListResponse", "FileSummaryResponse", "HealthResponse",
    "HealthWorkflow", "RunListResponse", "ScheduleResponse",
    "TransformRequest", "TransformResponse",
]
