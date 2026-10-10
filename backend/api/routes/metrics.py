import logging
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
from backend.database.errors import MetricsDataIntegrityError, MetricsStoreUnavailable
from backend.database.service.metrics.scope import MetricsScope

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_session)])

MetricsServiceDependency = Annotated[MetricsService, Depends(get_metrics_service)]
Session = Annotated[AuthSession, Depends(require_session)]


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="metrics store unavailable")


def _data_integrity() -> HTTPException:
    return HTTPException(status_code=500, detail="metrics data integrity error")


def _scope(session: AuthSession) -> MetricsScope:
    return MetricsScope.facility(session.facility_id)


@router.get("/period-summary", response_model=list[PeriodSummaryMetric])
async def get_period_summary(
    query: Annotated[MetricsGrainQuery, Query()],
    service: MetricsServiceDependency,
    session: Session,
) -> list[PeriodSummaryMetric]:
    scope = _scope(session)
    try:
        return await service.period_summary(scope, query.grain)
    except MetricsStoreUnavailable as exc:
        logger.warning(
            "metrics store unavailable endpoint=%s model=%s facility_id=%s grain=%s error=%s",
            "period-summary",
            "PeriodSummaryMetric",
            session.facility_id,
            query.grain,
            type(exc).__name__,
        )
        raise _unavailable() from exc
    except MetricsDataIntegrityError as exc:
        logger.error(
            "metrics data integrity error endpoint=%s model=%s facility_id=%s grain=%s error=%s",
            "period-summary",
            "PeriodSummaryMetric",
            session.facility_id,
            query.grain,
            type(exc).__name__,
        )
        raise _data_integrity() from exc


@router.get("/comorbidity", response_model=list[ComorbidityMetric])
async def get_comorbidity(
    query: Annotated[MetricsGrainQuery, Query()],
    service: MetricsServiceDependency,
    session: Session,
) -> list[ComorbidityMetric]:
    scope = _scope(session)
    try:
        return await service.comorbidity(scope, query.grain)
    except MetricsStoreUnavailable as exc:
        logger.warning(
            "metrics store unavailable endpoint=%s model=%s facility_id=%s grain=%s error=%s",
            "comorbidity",
            "ComorbidityMetric",
            session.facility_id,
            query.grain,
            type(exc).__name__,
        )
        raise _unavailable() from exc
    except MetricsDataIntegrityError as exc:
        logger.error(
            "metrics data integrity error endpoint=%s model=%s facility_id=%s grain=%s error=%s",
            "comorbidity",
            "ComorbidityMetric",
            session.facility_id,
            query.grain,
            type(exc).__name__,
        )
        raise _data_integrity() from exc


@router.get("/patient-state/out-of-control", response_model=list[PatientStateMetric])
async def get_out_of_control(
    query: Annotated[MetricsFacilityQuery, Query()],
    service: MetricsServiceDependency,
    session: Session,
) -> list[PatientStateMetric]:
    _ = query
    scope = _scope(session)
    try:
        return await service.out_of_control(scope)
    except MetricsStoreUnavailable as exc:
        logger.warning(
            "metrics store unavailable endpoint=%s model=%s facility_id=%s error=%s",
            "patient-state/out-of-control",
            "PatientStateMetric",
            session.facility_id,
            type(exc).__name__,
        )
        raise _unavailable() from exc
    except MetricsDataIntegrityError as exc:
        logger.error(
            "metrics data integrity error endpoint=%s model=%s facility_id=%s error=%s",
            "patient-state/out-of-control",
            "PatientStateMetric",
            session.facility_id,
            type(exc).__name__,
        )
        raise _data_integrity() from exc


@router.get("/data-quality", response_model=list[DataQualityMetric])
async def get_data_quality(
    query: Annotated[MetricsGrainQuery, Query()],
    service: MetricsServiceDependency,
    session: Session,
) -> list[DataQualityMetric]:
    scope = _scope(session)
    try:
        return await service.data_quality(scope, query.grain)
    except MetricsStoreUnavailable as exc:
        logger.warning(
            "metrics store unavailable endpoint=%s model=%s facility_id=%s grain=%s error=%s",
            "data-quality",
            "DataQualityMetric",
            session.facility_id,
            query.grain,
            type(exc).__name__,
        )
        raise _unavailable() from exc
    except MetricsDataIntegrityError as exc:
        logger.error(
            "metrics data integrity error endpoint=%s model=%s facility_id=%s grain=%s error=%s",
            "data-quality",
            "DataQualityMetric",
            session.facility_id,
            query.grain,
            type(exc).__name__,
        )
        raise _data_integrity() from exc


@router.get("/status", response_model=MetricsStatus)
async def get_metrics_status(
    query: Annotated[MetricsFacilityQuery, Query()],
    service: MetricsServiceDependency,
    session: Session,
) -> MetricsStatus:
    _ = (query, session)
    scope = _scope(session)
    try:
        return await service.status()
    except MetricsStoreUnavailable as exc:
        logger.warning(
            "metrics store unavailable endpoint=%s model=%s facility_id=%s error=%s",
            "status",
            "MetricsStatus",
            scope.facility_id,
            type(exc).__name__,
        )
        raise _unavailable() from exc
    except MetricsDataIntegrityError as exc:
        logger.error(
            "metrics data integrity error endpoint=%s model=%s facility_id=%s error=%s",
            "status",
            "MetricsStatus",
            scope.facility_id,
            type(exc).__name__,
        )
        raise _data_integrity() from exc


__all__ = ["router"]
