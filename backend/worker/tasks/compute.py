import logging
from asyncio import run
from dataclasses import replace

from backend.database.connection import task_pool_settings
from backend.database.service.staging.workflow_repository import WorkflowRunRepository
from backend.database.service.staging.workflow_schema import (
    TriggerType,
    WorkflowStatus,
    WorkflowType,
)
from backend.redis_cache.cache import MetricsCache

from ..app import celery
from ..compute_processor import ComputeProcessor
from ..resources import get_worker_redis, task_resources

logger = logging.getLogger(__name__)


@celery.task(bind=True, name="backend.worker.tasks.compute.compute_metrics")
def compute_metrics(self, force: bool = False, trigger: str = "SCHEDULED") -> None:
    run(_compute_metrics(
        force=force,
        trigger=trigger,
        celery_task_id=getattr(self.request, "id", None),
    ))


async def _compute_metrics(
    *, force: bool = False, trigger: str = "SCHEDULED", celery_task_id: str | None = None
) -> None:
    pool = replace(task_pool_settings(), pre_ping=True)
    async with task_resources(pool=pool) as resources:
        try:
            run_log = WorkflowRunRepository(resources.staging)
        except AttributeError:
            # Keep the task adapter usable with minimal resource fakes. Real
            # worker resources always expose async_session_local.
            run_log = None
        workflow_run_id = None
        if run_log is not None:
            try:
                workflow_run_id = await run_log.start(
                    WorkflowType.COMPUTATION.value,
                    TriggerType(trigger).value,
                    celery_task_id=celery_task_id,
                )
            except Exception as exc:  # noqa: BLE001 - run log bookkeeping must not fail task
                logger.warning("computation workflow run start failed error=%s", type(exc).__name__)

        try:
            outcome = await ComputeProcessor(
                production=resources.production,
                staging=resources.staging,
                metrics_cache=MetricsCache(get_worker_redis()),
            ).run(force=force)
        except Exception as exc:
            if workflow_run_id is not None:
                try:
                    await run_log.finish(
                        workflow_run_id,
                        WorkflowStatus.FAILED.value,
                        error_code="COMPUTATION_FAILED",
                        error_message=type(exc).__name__,
                    )
                except Exception as finish_error:  # noqa: BLE001 - run log bookkeeping must not fail task
                    logger.warning(
                        "computation workflow run finish failed error=%s",
                        type(finish_error).__name__,
                    )
            raise

        if workflow_run_id is not None:
            status = (
                WorkflowStatus.SUCCEEDED.value
                if outcome.status == "SUCCEEDED"
                else WorkflowStatus.SKIPPED.value
            )
            details = {} if status == WorkflowStatus.SUCCEEDED.value else {"outcome": outcome.status}
            try:
                await run_log.finish(
                    workflow_run_id,
                    status,
                    items_seen=outcome.rows_processed or 0,
                    details=details,
                    computation_run_id=outcome.computation_run_id,
                )
            except Exception as exc:  # noqa: BLE001 - run log bookkeeping must not fail task
                logger.warning("computation workflow run finish failed error=%s", type(exc).__name__)


__all__ = ["compute_metrics"]
