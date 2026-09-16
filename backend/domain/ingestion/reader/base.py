"""The domain-level reader abstraction."""

from abc import ABC, abstractmethod

from backend.domain.ingestion.contracts import SourceDataset


class SourceDatasetReader(ABC):
    """Reads one uploaded file without applying mapping or normalization."""

    @abstractmethod
    def read(self, file_bytes: bytes, filename: str) -> SourceDataset:
        """Return the raw source dataset represented by ``file_bytes``."""
