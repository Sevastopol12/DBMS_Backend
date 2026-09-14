import pandas as pd
from uuid import UUID

from backend.database.service import IngestionRepository, StorageService
from backend.database.schema import FileStatus

from backend.domain.ingestion import ColumnResolver, RowExaminer, ColumnResolution
from backend.domain.utils import serialize_error_log, _load_alias_cache
from backend.domain.models import TaskReport


class FileProcessor:
    def __init__(
        self,
        staging_repository: IngestionRepository,
        production_repository: IngestionRepository,
        storage: StorageService,
    ):
        self._staging = staging_repository
        self._production = production_repository
        self._storage = storage
        self._resolver = ColumnResolver(_load_alias_cache())
        self._examiner = RowExaminer()

    async def process_file(self, file_id: UUID):
        return file_id


__all__ = ["FileProcessor"]
