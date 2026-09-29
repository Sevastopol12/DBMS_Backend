from asyncio import run
from dataclasses import replace

from backend.database.connection import task_pool_settings
from backend.redis_cache.cache import MetricsCache

from ..app import celery
from ..compute_processor import ComputeProcessor
from ..resources import get_worker_redis, task_resources


@celery.task(name="backend.worker.tasks.compute.compute_metrics")
def compute_metrics(force: bool = False) -> None:
    run(_compute_metrics(force=force))


async def _compute_metrics(*, force: bool = False) -> None:
    pool = replace(task_pool_settings(), pre_ping=True)
    async with task_resources(pool=pool) as resources:
        await ComputeProcessor(
            production=resources.production,
            staging=resources.staging,
            metrics_cache=MetricsCache(get_worker_redis()),
        ).run(force=force)


__all__ = ["compute_metrics"]
