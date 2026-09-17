from ..app import celery
from uuid import UUID
from asyncio import run
from backend.domain.processor import FileProcessor, InfrastructureProcessingError
from backend.database import (
    get_staging_repository,
    get_production_repository,
    get_staging_storage,
)

@celery.task(
    bind=True,
    name="backend.celery.tasks.transform.transform",
    max_retries=3,
)
def transform(self, task_id: UUID):
    try:
        return run(_transform(task_id))
    except InfrastructureProcessingError as exc:
        # FileProcessor marks the attempt ERROR; only a pending retry becomes
        # claimable again.  The final failed attempt stays ERROR.
        if self.request.retries >= self.max_retries:
            raise
        run(get_staging_repository().requeue_for_retry(task_id))
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

async def _transform(task_id: UUID):
    processor = FileProcessor(
        staging_repository=get_staging_repository(),
        production_repository=get_production_repository(),
        storage=get_staging_storage(),
    )
    await processor.process_file(task_id)
