from asyncio import run
from uuid import UUID

from backend.database import load_header_mappings
from backend.database.service import IngestionRepository, StorageService
from backend.database.service.production.persistence import AcceptedDataPersistence
from backend.domain.processing.mapping.source.mapping_gateway import get_mapping_gateway

from ..app import celery
from ..file_processor import FileProcessor
from ..resources import task_resources


@celery.task(name="backend.worker.tasks.transform.transform")
def transform(task_id: UUID):
    run(_transform(UUID(str(task_id))))


async def _transform(task_id: UUID):
    async with task_resources() as res:
        processor = FileProcessor(
            staging_repository=IngestionRepository(res.staging),
            persistence=AcceptedDataPersistence(res.production),
            storage=StorageService(res.storage),
            mapping_provider=get_mapping_gateway(db_loader=load_header_mappings),
        )
        await processor.process_file(task_id)
