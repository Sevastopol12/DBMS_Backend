from typing import Any, Mapping
from .base import ValueExtractor
from .extractors import _raw, _lineage, _issue, ExtractionResult
from backend.domain.ingestion.normalization import clean_optional_text


class DirectExtractor(ValueExtractor):
    """Copy a single mapped source value with only null/whitespace handling."""

    def __init__(self, target_field: str) -> None:
        self.target_field = target_field

    def extract(
        self,
        value: Any = None,
        *,
        source_column: str | None = None,
        source_values: Mapping[str, Any] | None = None,
        row: Mapping[str, Any] | None = None,
    ) -> ExtractionResult:
        raw_values = _raw(source_column, value, source_values)
        if source_values is not None and len(source_values) != 1:
            return ExtractionResult(
                lineage=[_lineage(self.target_field, type(self).__name__, raw_values)],
                issues=[
                    _issue(
                        "AMBIGUOUS_SOURCE_VALUES",
                        "Direct extraction requires exactly one source value.",
                        raw_values,
                        [self.target_field],
                    )
                ],
            )
        raw_value = next(iter(raw_values.values()))
        return ExtractionResult(
            values={self.target_field: clean_optional_text(raw_value)},
            lineage=[_lineage(self.target_field, type(self).__name__, raw_values)],
        )
