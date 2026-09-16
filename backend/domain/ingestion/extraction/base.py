"""Common interface for pure, reusable value extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from .contracts import ExtractionResult


class ValueExtractor(ABC):
    """Extract canonical values without resolving a source column's meaning.

    Callers pass the target(s) selected by the mapping stage.  ``source_values``
    allows structural mappings to supply multiple values, while ``row`` is
    available for extractors that explicitly need the complete raw row.
    """

    @abstractmethod
    def extract(
        self,
        value: Any = None,
        *,
        source_column: str | None = None,
        source_values: Mapping[str, Any] | None = None,
        row: Mapping[str, Any] | None = None,
    ) -> ExtractionResult:
        """Return canonical values, their lineage, and explicit issues."""
