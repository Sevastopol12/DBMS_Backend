from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth.dependencies import require_session
from backend.api.auth.sessions import AuthSession
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
from backend.database.service.metrics.scope import MetricsScope

router = APIRouter(dependencies=[Depends(require_session)])

MetricsServiceDependency = Annotated[MetricsService, Depends(get_metrics_service)]
Session = Annotated[AuthSession, Depends(require_session)]


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="metrics store unavailable")


def _scope(session: AuthSession) -> MetricsScope:
    return MetricsScope.facility(session.facility_id)


@router.get("/period-summary", response_model=list[PeriodSummaryMetric])
async def get_period_summary(
    query: Annotated[MetricsGrainQuery, Query()],
    service: MetricsServiceDependency,
    session: Session,
) -> list[PeriodSummaryMetric]:
    try:
        return await service.period_summary(_scope(session), query.grain)
    except MetricsStoreUnavailable as exc:
        raise _unavailable() from exc


@router.get("/comorbidity", response_model=list[ComorbidityMetric])
async def get_comorbidity(
    query: Annotated[MetricsGrainQuery, Query()],
    service: MetricsServiceDependency,
    session: Session,
) -> list[ComorbidityMetric]:
    try:
        return await service.comorbidity(_scope(session), query.grain)
    except MetricsStoreUnavailable as exc:
        raise _unavailable() from exc


@router.get("/patient-state/out-of-control", response_model=list[PatientStateMetric])
async def get_out_of_control(
    query: Annotated[MetricsFacilityQuery, Query()],
    service: MetricsServiceDependency,
    session: Session,
) -> list[PatientStateMetric]:
    _ = query
    try:
        return await service.out_of_control(_scope(session))
    except MetricsStoreUnavailable as exc:
        raise _unavailable() from exc


@router.get("/data-quality", response_model=list[DataQualityMetric])
async def get_data_quality(
    query: Annotated[MetricsGrainQuery, Query()],
    service: MetricsServiceDependency,
    session: Session,
) -> list[DataQualityMetric]:
    try:
        return await service.data_quality(_scope(session), query.grain)
    except MetricsStoreUnavailable as exc:
        raise _unavailable() from exc


@router.get("/status", response_model=MetricsStatus)
async def get_metrics_status(
    query: Annotated[MetricsFacilityQuery, Query()],
    service: MetricsServiceDependency,
    session: Session,
) -> MetricsStatus:
    _ = (query, session)
    try:
        return await service.status()
    except MetricsStoreUnavailable as exc:
        raise _unavailable() from exc


__all__ = ["router"]
