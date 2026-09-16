"""Pure value extractors used after semantic mapping has selected targets."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .base import ValueExtractor
from .contracts import ExtractedValueLineage, ExtractionIssue, ExtractionResult

from backend.domain.ingestion.normalization import clean_optional_text
from backend.domain.ingestion.contracts import IssueSeverity


def _raw(
    source_column: str | None, value: Any, source_values: Mapping[str, Any] | None
) -> dict[str, Any]:
    if source_values is not None:
        return dict(source_values)
    return {source_column or "<value>": value}


def _lineage(
    target: str, extractor: str, raw_values: dict[str, Any]
) -> ExtractedValueLineage:
    return ExtractedValueLineage(
        target_field=target,
        extractor=extractor,
        source_columns=list(raw_values),
        raw_values=raw_values,
    )


def _issue(
    code: str, message: str, raw_values: dict[str, Any], targets: Sequence[str]
) -> ExtractionIssue:
    return ExtractionIssue(
        code=code,
        message=message,
        severity=IssueSeverity.ERROR,
        source_columns=list(raw_values),
        target_fields=list(targets),
        raw_values=raw_values,
    )


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
