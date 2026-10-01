from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.dependencies import get_metrics_service
from backend.api.dto import (
    ComorbidityMetric,
    DataQualityMetric,
    MetricsFacilityQuery,
    MetricsGrainQuery,
    MetricsStatus,
    PatientStateMetric,
    PeriodSummaryMetric,
)
from backend.api.metrics_service import MetricsService
from backend.database.errors import MetricsStoreUnavailable

router = APIRouter()

MetricsServiceDependency = Annotated[MetricsService, Depends(get_metrics_service)]


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="metrics store unavailable")


@router.get("/period-summary", response_model=list[PeriodSummaryMetric])
async def get_period_summary(
    query: Annotated[MetricsGrainQuery, Query()],
    service: MetricsServiceDependency,
) -> list[PeriodSummaryMetric]:
    try:
        return await service.period_summary(query.facility_id, query.grain)
    except MetricsStoreUnavailable as exc:
        raise _unavailable() from exc


@router.get("/comorbidity", response_model=list[ComorbidityMetric])
async def get_comorbidity(
    query: Annotated[MetricsGrainQuery, Query()],
    service: MetricsServiceDependency,
) -> list[ComorbidityMetric]:
    try:
        return await service.comorbidity(query.facility_id, query.grain)
    except MetricsStoreUnavailable as exc:
        raise _unavailable() from exc


@router.get("/patient-state/out-of-control", response_model=list[PatientStateMetric])
async def get_out_of_control(
    query: Annotated[MetricsFacilityQuery, Query()],
    service: MetricsServiceDependency,
) -> list[PatientStateMetric]:
    try:
        return await service.out_of_control(query.facility_id)
    except MetricsStoreUnavailable as exc:
        raise _unavailable() from exc


@router.get("/data-quality", response_model=list[DataQualityMetric])
async def get_data_quality(
    query: Annotated[MetricsGrainQuery, Query()],
    service: MetricsServiceDependency,
) -> list[DataQualityMetric]:
    try:
        return await service.data_quality(query.facility_id, query.grain)
    except MetricsStoreUnavailable as exc:
        raise _unavailable() from exc


@router.get("/status", response_model=MetricsStatus)
async def get_metrics_status(service: MetricsServiceDependency) -> MetricsStatus:
    try:
        return await service.status()
    except MetricsStoreUnavailable as exc:
        raise _unavailable() from exc


__all__ = ["router"]
