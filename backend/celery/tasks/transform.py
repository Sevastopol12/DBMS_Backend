from uuid import UUID
from asyncio import run

from ..app import celery
from backend.domain.processor import FileProcessor
from backend.database import (
    get_staging_repository,
    get_production_repository,
    get_staging_storage,
)
from backend.mapping_gateway import get_mapping_gateway


@celery.task(name="backend.celery.tasks.transform.transform")
def transform(task_id: UUID):
    run(_transform(task_id))


async def _transform(task_id: UUID):
    processor = FileProcessor(
        staging_repository=get_staging_repository(),
        production_repository=get_production_repository(),
        storage=get_staging_storage(),
        mapping_provider=get_mapping_gateway(),
    )
    await processor.process_file(task_id)
