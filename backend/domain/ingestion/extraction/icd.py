import re
from typing import Any, Sequence, Mapping
from .base import ValueExtractor
from .extractors import _raw, _lineage, _issue, ExtractionResult
from backend.domain.ingestion.normalization import clean_optional_text

class ICDExtractor(ValueExtractor):
    """Copy ICD text, or split combined values only with caller-provided rules."""

    def __init__(
        self,
        target_field: str | None = None,
        *,
        target_fields: Sequence[str] | None = None,
        separators: Sequence[str] = ("/",),
    ) -> None:
        if (target_field is None) == (target_fields is None):
            raise ValueError("Provide exactly one of target_field or target_fields")
        self.targets = (
            (target_field,) if target_field is not None else tuple(target_fields or ())
        )
        if (
            not self.targets
            or not separators
            or any(not separator for separator in separators)
        ):
            raise ValueError(
                "ICD targets and explicit non-empty separators are required"
            )
        self.separators = tuple(separators)

    def extract(
        self,
        value: Any = None,
        *,
        source_column: str | None = None,
        source_values: Mapping[str, Any] | None = None,
        row: Mapping[str, Any] | None = None,
    ) -> ExtractionResult:
        raw_values = _raw(source_column, value, source_values)
        lineage = [
            _lineage(target, type(self).__name__, raw_values) for target in self.targets
        ]
        if source_values is not None and len(source_values) != 1:
            return ExtractionResult(
                lineage=lineage,
                issues=[
                    _issue(
                        "AMBIGUOUS_SOURCE_VALUES",
                        "ICD extraction requires one source value.",
                        raw_values,
                        self.targets,
                    )
                ],
            )
        text = clean_optional_text(next(iter(raw_values.values())))
        if text is None:
            return ExtractionResult(values=dict.fromkeys(self.targets), lineage=lineage)
        if len(self.targets) == 1:
            return ExtractionResult(values={self.targets[0]: text}, lineage=lineage)
        parts = [
            part.strip()
            for part in re.split("|".join(re.escape(s) for s in self.separators), text)
        ]
        if len(parts) != len(self.targets) or not all(parts):
            return ExtractionResult(
                lineage=lineage,
                issues=[
                    _issue(
                        "MALFORMED_COMBINED_ICD",
                        "Combined ICD value does not match the explicitly configured target count and separator.",
                        raw_values,
                        self.targets,
                    )
                ],
            )
        return ExtractionResult(
            values=dict(zip(self.targets, parts, strict=True)), lineage=lineage
        )
