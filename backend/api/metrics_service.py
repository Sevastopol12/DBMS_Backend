"""Cache-first service for typed dashboard metric responses."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Protocol, TypeVar
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from backend.api.dto import (
    ComorbidityMetric,
    DataQualityMetric,
    MetricsStatus,
    PatientStateMetric,
    PeriodSummaryMetric,
)
from backend.database.errors import MetricsDataIntegrityError
from backend.database.service.metrics.scope import MetricsScope
from backend.redis_cache.cache import MetricsCache
from backend.redis_cache.keys import (
    LAST_COMPUTED_AT_KEY,
    METRICS_CACHE_TTL_SECONDS,
    comorbidity_key,
    data_quality_key,
    out_of_control_key,
    period_summary_key,
)

logger = logging.getLogger(__name__)


def _field_paths(exc: ValidationError) -> list[str]:
    """Pydantic ``loc`` paths only — never row values (no PII in logs)."""
    return [
        ".".join(str(part) for part in error.get("loc", ())) for error in exc.errors()
    ]


def _sanitized_errors(exc: ValidationError) -> list[dict]:
    """Error loc/msg/type only — never ``input``/``ctx`` row content."""
    return [
        {
            "loc": error.get("loc", ()),
            "msg": error.get("msg"),
            "type": error.get("type"),
        }
        for error in exc.errors()
    ]


class MetricsReadRepositoryProtocol(Protocol):
    async def period_summary(
        self, scope: MetricsScope, grain: str, *, run_id: UUID | None = None
    ) -> list[dict]: ...

    async def comorbidity(
        self, scope: MetricsScope, grain: str, *, run_id: UUID | None = None
    ) -> list[dict]: ...

    async def out_of_control(
        self, scope: MetricsScope, *, run_id: UUID | None = None
    ) -> list[dict]: ...

    async def data_quality(
        self, scope: MetricsScope, grain: str, *, run_id: UUID | None = None
    ) -> list[dict]: ...

    async def last_computed_at(
        self, *, run_id: UUID | None = None
    ) -> datetime | None: ...


MetricModel = TypeVar("MetricModel")


class MetricsService:
    def __init__(
        self,
        cache: MetricsCache,
        repository: MetricsReadRepositoryProtocol,
    ) -> None:
        self._cache = cache
        self._repository = repository

    async def _cached_rows(
        self,
        key: str,
        adapter: TypeAdapter[list[MetricModel]],
        *,
        metric: str = "unknown",
        facility_id: str | None = None,
        grain: str | None = None,
    ) -> list[MetricModel] | None:
        try:
            value = await asyncio.to_thread(self._cache.get, key)
        except Exception as exc:  # noqa: BLE001 - best-effort cache; never raise
            logger.warning(
                "metrics cache read failed metric=%s facility_id=%s grain=%s key=%s error=%s",
                metric,
                facility_id,
                grain,
                key,
                type(exc).__name__,
            )
            return None
        if value is None:
            return None
        try:
            return adapter.validate_python(value)
        except ValidationError as exc:
            logger.warning(
                "invalid metrics cache payload metric=%s facility_id=%s grain=%s key=%s error=%s fields=%s",
                metric,
                facility_id,
                grain,
                key,
                type(exc).__name__,
                _field_paths(exc),
            )
            return None

    async def _write_rows(
        self,
        key: str,
        models: list[MetricModel],
        *,
        metric: str = "unknown",
        facility_id: str | None = None,
        grain: str | None = None,
    ) -> None:
        try:
            payload = [model.model_dump(mode="json") for model in models]
            await asyncio.to_thread(
                self._cache.set,
                key,
                payload,
                ttl_seconds=METRICS_CACHE_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort cache; never raise
            logger.warning(
                "metrics cache write failed metric=%s facility_id=%s grain=%s key=%s error=%s",
                metric,
                facility_id,
                grain,
                key,
                type(exc).__name__,
            )

    async def _get_rows(
        self,
        key: str,
        adapter: TypeAdapter[list[MetricModel]],
        loader,
        *,
        metric: str = "unknown",
        facility_id: str | None = None,
        grain: str | None = None,
    ) -> list[MetricModel]:
        cached = await self._cached_rows(
            key, adapter, metric=metric, facility_id=facility_id, grain=grain
        )
        if cached is not None:
            return cached
        rows = await loader()
        try:
            models = adapter.validate_python(rows)
        except ValidationError as exc:
            try:
                row_count = len(rows)  # type: ignore[arg-type]
            except TypeError:
                row_count = -1
            logger.error(
                "invalid metrics database payload metric=%s facility_id=%s grain=%s key=%s error=%s row_count=%s fields=%s errors=%s",
                metric,
                facility_id,
                grain,
                key,
                type(exc).__name__,
                row_count,
                _field_paths(exc),
                _sanitized_errors(exc),
            )
            raise MetricsDataIntegrityError(key) from exc
        await self._write_rows(
            key, models, metric=metric, facility_id=facility_id, grain=grain
        )
        return models

    async def period_summary(
        self, scope: MetricsScope, grain: str
    ) -> list[PeriodSummaryMetric]:
        return await self._get_rows(
            period_summary_key(scope.token, grain),
            TypeAdapter(list[PeriodSummaryMetric]),
            lambda: self._repository.period_summary(scope, grain),
            metric="period_summary",
            facility_id=scope.token,
            grain=grain,
        )

    async def comorbidity(
        self, scope: MetricsScope, grain: str
    ) -> list[ComorbidityMetric]:
        return await self._get_rows(
            comorbidity_key(scope.token, grain),
            TypeAdapter(list[ComorbidityMetric]),
            lambda: self._repository.comorbidity(scope, grain),
            metric="comorbidity",
            facility_id=scope.token,
            grain=grain,
        )

    async def out_of_control(self, scope: MetricsScope) -> list[PatientStateMetric]:
        return await self._get_rows(
            out_of_control_key(scope.token),
            TypeAdapter(list[PatientStateMetric]),
            lambda: self._repository.out_of_control(scope),
            metric="out_of_control",
            facility_id=scope.token,
            grain=None,
        )

    async def data_quality(
        self, scope: MetricsScope, grain: str
    ) -> list[DataQualityMetric]:
        return await self._get_rows(
            data_quality_key(scope.token, grain),
            TypeAdapter(list[DataQualityMetric]),
            lambda: self._repository.data_quality(scope, grain),
            metric="data_quality",
            facility_id=scope.token,
            grain=grain,
        )

    async def status(self) -> MetricsStatus:
        try:
            value = await asyncio.to_thread(self._cache.get, LAST_COMPUTED_AT_KEY)
        except Exception as exc:  # noqa: BLE001 - best-effort cache; never raise
            logger.warning(
                "metrics cache read failed metric=%s key=%s error=%s",
                "status",
                LAST_COMPUTED_AT_KEY,
                type(exc).__name__,
            )
            value = None
        if value is not None:
            try:
                timestamp = TypeAdapter(datetime).validate_python(value)
            except ValidationError as exc:
                logger.warning(
                    "invalid metrics cache payload metric=%s key=%s error=%s fields=%s",
                    "status",
                    LAST_COMPUTED_AT_KEY,
                    type(exc).__name__,
                    _field_paths(exc),
                )
            else:
                return MetricsStatus(last_computed_at=timestamp)

        return MetricsStatus(last_computed_at=await self._repository.last_computed_at())


__all__ = [
    "MetricsReadRepositoryProtocol",
    "MetricsService",
]
