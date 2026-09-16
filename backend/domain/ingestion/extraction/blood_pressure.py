import re
from typing import Any, Sequence, Mapping
from .base import ValueExtractor
from .extractors import _raw, _lineage, _issue, ExtractionResult
from backend.domain.ingestion.normalization import clean_optional_text


class BloodPressureExtractor(ValueExtractor):
    """Split an explicitly delimited blood-pressure string; no clinical validation."""

    def __init__(
        self,
        *,
        systolic_field: str = "huyet_ap_tam_thu",
        diastolic_field: str = "huyet_ap_tam_truong",
        separators: Sequence[str] = ("/",),
    ) -> None:
        if not separators or any(not separator for separator in separators):
            raise ValueError("At least one non-empty explicit separator is required")
        self.targets = (systolic_field, diastolic_field)
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
                        "Blood-pressure extraction requires one composite source value.",
                        raw_values,
                        self.targets,
                    )
                ],
            )
        text = clean_optional_text(next(iter(raw_values.values())))
        if text is None:
            return ExtractionResult(values=dict.fromkeys(self.targets), lineage=lineage)
        pattern = "|".join(re.escape(separator) for separator in self.separators)
        parts = re.split(pattern, text)
        if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
            return ExtractionResult(
                lineage=lineage,
                issues=[
                    _issue(
                        "MALFORMED_BLOOD_PRESSURE",
                        "Blood pressure must contain two integer components separated by an explicitly configured separator.",
                        raw_values,
                        self.targets,
                    )
                ],
            )
        return ExtractionResult(
            values={
                self.targets[0]: parts[0].strip(),
                self.targets[1]: parts[1].strip(),
            },
            lineage=lineage,
        )
