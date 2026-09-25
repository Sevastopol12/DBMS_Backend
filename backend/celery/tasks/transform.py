from uuid import UUID
from asyncio import run

from ..app import celery
from ..resources import task_resources
from backend.domain.processor import FileProcessor
from backend.database.service import IngestionRepository, StorageService
from backend.database.service.repository.production import ReportRepository
from backend.mapping_gateway import get_mapping_gateway


@celery.task(name="backend.celery.tasks.transform.transform")
def transform(task_id: UUID):
    run(_transform(task_id))


async def _transform(task_id: UUID):
    async with task_resources() as res:
        processor = FileProcessor(
            staging_repository=IngestionRepository(res.staging),
            production_repository=ReportRepository(res.production),
            storage=StorageService(res.storage),
            mapping_provider=get_mapping_gateway(),
        )
        await processor.process_file(task_id)
