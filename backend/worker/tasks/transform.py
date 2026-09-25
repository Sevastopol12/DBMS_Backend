from uuid import UUID
from asyncio import run

from ..app import celery
from ..resources import task_resources
from ..file_processor import FileProcessor
from backend.database.service import (
    IngestionRepository,
    ReportRepository,
    StorageService,
)
from backend.domain.processing.mapping.source.mapping_gateway import get_mapping_gateway
from backend.database import load_header_mappings


@celery.task(name="backend.worker.tasks.transform.transform")
def transform(task_id: UUID):
    run(_transform(task_id))


async def _transform(task_id: UUID):
    async with task_resources() as res:
        processor = FileProcessor(
            staging_repository=IngestionRepository(res.staging),
            production_repository=ReportRepository(res.production),
            storage=StorageService(res.storage),
            mapping_provider=get_mapping_gateway(db_loader=load_header_mappings),
        )
        await processor.process_file(task_id)
