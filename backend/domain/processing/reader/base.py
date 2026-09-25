from abc import ABC, abstractmethod
from uuid import UUID

from ..models import SourceDataset


class SourceDatasetReader(ABC):
    """Reads one uploaded file without applying mapping or normalization."""

    @abstractmethod
    def read(
        self, file_bytes: bytes, filename: str, source_file_id: UUID
    ) -> SourceDataset:
        """Return the raw source dataset represented by ``file_bytes``."""


__all__ = ["SourceDatasetReader"]
