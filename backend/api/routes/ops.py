from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend.api.dependencies import (
    AcceptedDataRepositoryDep,
    IngestionRepositoryDep,
    MetricsRepositoryDep,
    WorkflowRunRepositoryDep,
    get_resources,
)
from backend.api.ops_dto import (
    ComputeRequest,
    ComputeResponse,
    FileDetailResponse,
    FileListResponse,
    FileSummaryResponse,
    HealthResponse,
    RunListResponse,
    ScheduleResponse,
    TransformRequest,
    TransformResponse,
)
from backend.api.ops_service import OpsService
from backend.database.errors import MetricsStoreUnavailable

router = APIRouter()


def get_ops_service(
    request: Request,
    ingestion: IngestionRepositoryDep,
    workflow: WorkflowRunRepositoryDep,
    reports: AcceptedDataRepositoryDep,
    metrics: MetricsRepositoryDep,
) -> OpsService:
    return OpsService(
        resources=get_resources(request),
        ingestion=ingestion,
        workflow=workflow,
        reports=reports,
        metrics=metrics,
    )


Service = Annotated[OpsService, Depends(get_ops_service)]


@router.post(
    "/transform", response_model=TransformResponse, status_code=status.HTTP_202_ACCEPTED
)
async def post_transform(request: TransformRequest, service: Service):
    try:
        return await service.transform_files(request)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.post(
    "/compute", response_model=ComputeResponse, status_code=status.HTTP_202_ACCEPTED
)
async def post_compute(request: ComputeRequest, service: Service):
    return {"task_id": await service.dispatch_compute(request.force)}


@router.get("/health", response_model=HealthResponse)
async def get_health(service: Service):
    return await service.health()


@router.get("/files/summary", response_model=FileSummaryResponse)
async def get_file_summary(service: Service, facility_id: UUID | None = None):
    return await service.file_summary(facility_id)


@router.get("/files", response_model=FileListResponse)
async def get_files(
    service: Service,
    status: str | None = None,
    error_code: str | None = None,
    facility_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return {
        "items": await service.ingestion.list_files(
            status=status,
            error_code=error_code,
            facility_id=facility_id,
            limit=limit,
            offset=offset,
        ),
        "limit": limit,
        "offset": offset,
    }


@router.get("/files/{file_id}", response_model=FileDetailResponse)
async def get_file(file_id: UUID, service: Service):
    detail = await service.ingestion.get_detail(file_id)
    if detail is None:
        raise HTTPException(404, detail="file not found")
    detail["production"] = dict(
        zip(
            ("report_rows", "review_rows"),
            await service.reports.count_for_file(file_id),
        )
    )
    return detail


@router.get("/runs", response_model=RunListResponse)
async def get_runs(
    service: Service,
    workflow_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    return {
        "items": await service.workflow.recent(workflow_type=workflow_type, limit=limit)
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, service: Service):
    value = await service.workflow.get(run_id)
    if value is None:
        raise HTTPException(404, detail="run not found")
    return value


@router.get("/compute/runs")
async def get_compute_runs(service: Service, limit: int = Query(20, ge=1, le=200)):
    try:
        return {"items": await service.metrics.recent_runs(limit=limit)}
    except MetricsStoreUnavailable as exc:
        raise HTTPException(503, detail="metrics store unavailable") from exc


@router.get("/schedule", response_model=ScheduleResponse)
async def get_schedule(service: Service):
    return await service.schedule()


__all__ = ["get_ops_service", "router"]
