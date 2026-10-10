from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any
from uuid import UUID

from redbeat.decoder import RedBeatJSONDecoder
from starlette.concurrency import run_in_threadpool

from backend.database.service.staging.workflow_schema import (
    TriggerType,
    WorkflowStatus,
    WorkflowType,
)
from backend.timezone import VIETNAM_TZ, now_vietnam
from backend.worker.tasks.compute import compute_metrics
from backend.worker.tasks.transform import transform

logger = logging.getLogger(__name__)
_STATUS_ORDER = ("CREATED", "QUEUED", "PROCESSING", "SUCCEED", "REJECTED", "ERROR")


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode()
    return value


def _interval_seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        if value.get("__type__") == "interval":
            return float(value.get("every", 0))
        if "every" in value:
            return float(value["every"])
    run_every = getattr(value, "run_every", None)
    if run_every is not None:
        return float(run_every.total_seconds())
    return None


class OpsService:
    def __init__(self, *, resources, ingestion, workflow, reports, metrics) -> None:
        self.resources = resources
        self.ingestion = ingestion
        self.workflow = workflow
        self.reports = reports
        self.metrics = metrics

    async def transform_files(self, request) -> dict:
        request.validate_selector()
        run_id = await self.workflow.start(
            WorkflowType.TRANSFORM_MANUAL.value,
            TriggerType.MANUAL.value,
        )
        try:
            result = await self.ingestion.requeue(
                file_ids=request.file_ids,
                statuses=request.statuses,
                allow_rejected=request.force,
            )
            selected_ids = [*result.requeued, *result.already_queued]
            dispatched = 0
            dispatch_failed = 0
            for index in range(0, len(selected_ids), 500):
                for file_id in selected_ids[index : index + 500]:
                    try:
                        await run_in_threadpool(
                            transform.apply_async, args=[str(file_id)]
                        )
                    except Exception as exc:  # noqa: BLE001 - resilience boundary: dispatch loop fails open
                        dispatch_failed += 1
                        logger.warning(
                            "transform dispatch failed error=%s", type(exc).__name__
                        )
                    else:
                        dispatched += 1

            skipped_by_reason: dict[str, int] = {}
            skipped = []
            for file_id, reason in result.skipped.items():
                skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
                if len(skipped) < 100:
                    skipped.append({"file_id": str(file_id), "reason": reason})
            skipped_total = len(result.skipped)
            status = (
                WorkflowStatus.PARTIAL.value
                if dispatch_failed
                else WorkflowStatus.SUCCEEDED.value
            )
            await self.workflow.finish(
                run_id,
                status,
                items_seen=len(selected_ids) + skipped_total,
                items_dispatched=dispatched,
                items_skipped=skipped_total,
                items_failed=dispatch_failed,
                details={"skipped_by_reason": skipped_by_reason},
            )
            return {
                "run_id": run_id,
                "selected": len(selected_ids) + skipped_total,
                "requeued": len(result.requeued),
                "already_queued": len(result.already_queued),
                "dispatched": dispatched,
                "dispatch_failed": dispatch_failed,
                "skipped_total": skipped_total,
                "skipped_by_reason": skipped_by_reason,
                "skipped": skipped,
            }
        except Exception as exc:
            try:
                await self.workflow.finish(
                    run_id,
                    WorkflowStatus.FAILED.value,
                    error_code="DISPATCH_FAILED",
                    error_message=type(exc).__name__,
                )
            except Exception as finish_error:  # noqa: BLE001 - resilience boundary: run-log update best effort
                logger.warning(
                    "ops transform run finish failed error=%s",
                    type(finish_error).__name__,
                )
            raise

    async def dispatch_compute(self, force: bool) -> str:
        result = await run_in_threadpool(
            compute_metrics.apply_async,
            kwargs={"force": force, "trigger": TriggerType.MANUAL.value},
        )
        return str(result.id)

    async def health(self) -> dict:
        checks = {
            "staging_db": await self._probe_db(self.resources.staging),
            "application_db": await self._probe_db(self.resources.application),
            "redis": await self._probe_redis(),
        }
        latest = await self.workflow.latest_by_type()
        workflows = {}
        for workflow_type, env_name, default in (
            (
                WorkflowType.TRANSFORM_SWEEP.value,
                "TRANSFORM_SWEEP_INTERVAL_SECONDS",
                28800,
            ),
            (WorkflowType.COMPUTATION.value, "COMPUTE_INTERVAL_SECONDS", 1800),
        ):
            interval = int(os.getenv(env_name, str(default)))
            last = latest.get(workflow_type)
            overdue = (
                None
                if last is None
                else self._overdue(last.get("started_at"), interval)
            )
            workflows[workflow_type] = {
                "last_run": last,
                "expected_interval_seconds": interval,
                "overdue": overdue,
            }
        degraded = not all(checks.values()) or any(
            v["overdue"] is True for v in workflows.values()
        )
        return {
            "status": "degraded" if degraded else "ok",
            "checks": checks,
            "workflows": workflows,
        }

    async def _probe_db(self, config) -> bool:
        async def probe():
            from sqlalchemy import text

            async with config.async_engine.connect() as connection:
                await connection.execute(text("SELECT 1"))

        try:
            await asyncio.wait_for(probe(), timeout=2.0)
        except Exception as exc:  # noqa: BLE001 - resilience boundary: health probe fails open
            logger.warning(
                "ops database health check failed error=%s", type(exc).__name__
            )
            return False
        return True

    async def _probe_redis(self) -> bool:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self.resources.redis.ping), timeout=2.0
            )
        except Exception as exc:  # noqa: BLE001 - resilience boundary: health probe fails open
            logger.warning("ops redis health check failed error=%s", type(exc).__name__)
            return False
        return True

    @staticmethod
    def _overdue(started_at, interval: int) -> bool:
        if started_at is None:
            return True
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=VIETNAM_TZ)
        return (
            now_vietnam() - started_at.astimezone(VIETNAM_TZ)
        ).total_seconds() > 2 * interval

    async def file_summary(self, facility_id: UUID | None) -> dict:
        counts = await self.ingestion.status_counts(facility_id=facility_id)
        by_status = {status: counts.get(status, 0) for status in _STATUS_ORDER}
        oldest = await self.ingestion.oldest_queued_at()
        now = now_vietnam()
        age = (
            None
            if oldest is None
            else max(0.0, (now - oldest.astimezone(VIETNAM_TZ)).total_seconds())
        )
        return {
            "total": sum(by_status.values()),
            "by_status": by_status,
            "errors": {
                **(
                    await self.ingestion.retry_buckets(
                        max_attempts=int(os.getenv("TRANSFORM_MAX_ATTEMPTS", "3")),
                        facility_id=facility_id,
                    )
                ),
                "by_code": await self.ingestion.error_code_counts(
                    status="ERROR", facility_id=facility_id
                ),
            },
            "rejected_by_code": await self.ingestion.error_code_counts(
                status="REJECTED", facility_id=facility_id
            ),
            "oldest_queued_at": oldest,
            "oldest_queued_age_seconds": age,
            "last_completed_at": await self.ingestion.last_completed_at(
                facility_id=facility_id
            ),
        }

    async def schedule(self) -> dict:
        try:
            prefix = os.getenv("REDBEAT_KEY_PREFIX", "redbeat:")
            entries = []
            for name in ("compute-metrics-every-30-min", "transform-sweep-every-8h"):
                raw_definition = self.resources.redis.hget(
                    f"{prefix}{name}", "definition"
                )
                raw_meta = self.resources.redis.hget(f"{prefix}{name}", "meta")
                if not raw_definition:
                    continue
                definition = json.loads(
                    _json_value(raw_definition), cls=RedBeatJSONDecoder
                )
                meta = (
                    json.loads(_json_value(raw_meta), cls=RedBeatJSONDecoder)
                    if raw_meta
                    else {}
                )
                last = meta.get("last_run_at")
                entries.append(
                    {
                        "name": name,
                        "task": definition.get("task", ""),
                        "interval_seconds": _interval_seconds(
                            definition.get("schedule")
                        ),
                        "last_run_at": last,
                        "total_run_count": int(meta.get("total_run_count", 0)),
                    }
                )
            return {"available": True, "entries": entries}
        except Exception as exc:  # noqa: BLE001 - resilience boundary: schedule read fails open
            logger.warning("ops schedule read failed error=%s", type(exc).__name__)
            return {"available": False, "entries": []}


__all__ = ["OpsService"]
