from typing import Any, Sequence, Mapping
from .base import ValueExtractor
from .extractors import _raw, _lineage, _issue, ExtractionResult
from backend.domain.ingestion.normalization import clean_optional_text, normalized_token


class GenderExtractor(ValueExtractor):
    """Extract explicitly configured gender labels or indicator-column values."""

    DEFAULT_LABELS = {
        "nam": "Nam",
        "m": "Nam",
        "male": "Nam",
        "nu": "Nữ",
        "f": "Nữ",
        "female": "Nữ",
    }
    DEFAULT_ACTIVE_MARKERS = frozenset({"x", "yes", "true", "checked"})

    def __init__(
        self,
        target_field: str = "gioi_tinh",
        *,
        labels: Mapping[str, str] | None = None,
        indicator_columns: Mapping[str, str] | None = None,
        active_markers: Sequence[str] | None = None,
    ) -> None:
        self.target_field = target_field
        self.labels = {
            normalized_token(k): v for k, v in (labels or self.DEFAULT_LABELS).items()
        }
        self.indicator_columns = {
            normalized_token(k): v for k, v in (indicator_columns or {}).items()
        }
        self.active_markers = frozenset(
            normalized_token(v) for v in (active_markers or self.DEFAULT_ACTIVE_MARKERS)
        )

    def extract(
        self,
        value: Any = None,
        *,
        source_column: str | None = None,
        source_values: Mapping[str, Any] | None = None,
        row: Mapping[str, Any] | None = None,
    ) -> ExtractionResult:
        raw_values = _raw(source_column, value, source_values)
        lineage = [_lineage(self.target_field, type(self).__name__, raw_values)]
        if source_values is not None:
            configured = [
                (column, raw)
                for column, raw in source_values.items()
                if normalized_token(column) in self.indicator_columns
            ]
            if not configured:
                return ExtractionResult(
                    lineage=lineage,
                    issues=[
                        _issue(
                            "UNCONFIGURED_INDICATOR_COLUMNS",
                            "No supplied indicator column has an explicit gender rule.",
                            raw_values,
                            [self.target_field],
                        )
                    ],
                )
            active = [
                (column, self.indicator_columns[normalized_token(column)])
                for column, raw in configured
                if normalized_token(raw) in self.active_markers
            ]
            if len(active) == 1:
                return ExtractionResult(
                    values={self.target_field: active[0][1]}, lineage=lineage
                )
            if len(active) > 1:
                return ExtractionResult(
                    lineage=lineage,
                    issues=[
                        _issue(
                            "AMBIGUOUS_GENDER_INDICATORS",
                            "More than one configured gender indicator is active.",
                            raw_values,
                            [self.target_field],
                        )
                    ],
                )
            if all(clean_optional_text(raw) is None for _, raw in configured):
                return ExtractionResult(
                    values={self.target_field: None}, lineage=lineage
                )
            return ExtractionResult(
                lineage=lineage,
                issues=[
                    _issue(
                        "UNKNOWN_GENDER_INDICATOR",
                        "Configured gender indicators contain no explicit active marker.",
                        raw_values,
                        [self.target_field],
                    )
                ],
            )
        token = normalized_token(value)
        if token is None:
            return ExtractionResult(values={self.target_field: None}, lineage=lineage)
        if token in self.labels:
            return ExtractionResult(
                values={self.target_field: self.labels[token]}, lineage=lineage
            )
        return ExtractionResult(
            lineage=lineage,
            issues=[
                _issue(
                    "UNKNOWN_GENDER",
                    "Gender value does not match an explicit configured label.",
                    raw_values,
                    [self.target_field],
                )
            ],
        )
