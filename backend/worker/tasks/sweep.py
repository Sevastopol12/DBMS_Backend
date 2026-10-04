from asyncio import run

from backend.database.service import IngestionRepository
from backend.database.service.staging.workflow_repository import WorkflowRunRepository

from ..app import celery
from ..resources import task_resources
from ..settings import SweepSettings
from ..sweep_processor import SweepProcessor
from .transform import transform


@celery.task(bind=True, name="backend.worker.tasks.sweep.transform_sweep")
def transform_sweep(self, trigger: str = "SCHEDULED") -> None:
    run(_transform_sweep(trigger=trigger, celery_task_id=getattr(self.request, "id", None)))


async def _transform_sweep(*, trigger: str, celery_task_id: str | None = None) -> None:
    async with task_resources() as resources:
        processor = SweepProcessor(
            IngestionRepository(resources.staging),
            WorkflowRunRepository(resources.staging),
            dispatch=lambda file_id: transform.apply_async(args=[str(file_id)]),
            settings=SweepSettings.from_env(),
        )
        await processor.run(trigger=trigger, celery_task_id=celery_task_id)


__all__ = ["transform_sweep"]
