from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from backend.database.service.staging.workflow_schema import (
    TriggerType,
    WorkflowStatus,
    WorkflowType,
)

from .error_codes import DISPATCH_FAILED, SWEEP_FAILED
from .settings import SweepSettings

logger = logging.getLogger(__name__)


class SweepProcessor:
    def __init__(self, ingestion, workflow, dispatch: Callable[[UUID], None], settings: SweepSettings):
        self.ingestion = ingestion
        self.workflow = workflow
        self.dispatch = dispatch
        self.settings = settings

    async def run(self, *, trigger: str = "SCHEDULED", celery_task_id: str | None = None) -> None:
        run_id = None
        try:
            await self.workflow.reap_stale()
            run_id = await self.workflow.start(
                WorkflowType.TRANSFORM_SWEEP.value,
                TriggerType(trigger).value,
                celery_task_id=celery_task_id,
            )
            stale_queued = await self.ingestion.list_stale_queued(older_than=self.settings.queued_grace)
            recovered = await self.ingestion.recover_processing(processing_timeout=self.settings.processing_timeout)
            requeued = await self.ingestion.requeue_retryable_errors(max_attempts=self.settings.max_attempts)
            exhausted = await self.ingestion.count_exhausted_errors(max_attempts=self.settings.max_attempts)

            ids = list(dict.fromkeys([*stale_queued, *recovered, *requeued]))
            dispatch_errors: list[str] = []
            dispatched = 0
            for file_id in ids:
                try:
                    self.dispatch(file_id)
                    dispatched += 1
                except Exception as exc:  # noqa: BLE001 - one failure must not stop sweep
                    if len(dispatch_errors) < 5:
                        dispatch_errors.append(type(exc).__name__)
                    logger.warning("transform dispatch failed file_id=%s error=%s", file_id, type(exc).__name__)

            failed = len(ids) - dispatched
            status = (WorkflowStatus.SUCCEEDED.value if failed == 0 else
                      WorkflowStatus.PARTIAL.value if dispatched else WorkflowStatus.FAILED.value)
            details = {
                "recovered": len(recovered),
                "requeued": len(requeued),
                "stale_queued": len(stale_queued),
                "exhausted": exhausted,
            }
            if dispatch_errors:
                details["dispatch_errors"] = dispatch_errors
            await self.workflow.finish(
                run_id, status, items_seen=len(ids) + exhausted,
                items_dispatched=dispatched, items_skipped=exhausted, items_failed=failed,
                error_code=DISPATCH_FAILED if failed else None,
                error_message=DISPATCH_FAILED if failed else None,
                details=details,
            )
        except Exception as exc:
            if run_id is not None:
                try:
                    await self.workflow.finish(
                        run_id, WorkflowStatus.FAILED.value,
                        error_code=SWEEP_FAILED, error_message=type(exc).__name__,
                    )
                except Exception as finish_exc:  # noqa: BLE001 - finish must not mask original
                    logger.warning("transform sweep finish failed error=%s", type(finish_exc).__name__)
            raise
        finally:
            try:
                await self.workflow.prune(older_than=timedelta(days=self.settings.retention_days))
            except Exception as exc:  # noqa: BLE001 - prune in finally is best-effort
                logger.warning("transform sweep prune failed error=%s", type(exc).__name__)


__all__ = ["SweepProcessor"]
