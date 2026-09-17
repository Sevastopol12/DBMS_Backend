from typing import Any, Mapping

from .base import ValueExtractor
from .contracts import ExtractionResult
from .extractors import _issue, _lineage
from backend.domain.ingestion.normalization import clean_optional_text, normalized_token


class SplitNameExtractor(ValueExtractor):
    """Combine explicitly mapped surname/given-name source columns."""

    def __init__(self, target_field: str = "ho_ten") -> None:
        self.target_field = target_field

    def extract(
        self,
        value: Any = None,
        *,
        source_column: str | None = None,
        source_values: Mapping[str, Any] | None = None,
        row: Mapping[str, Any] | None = None,
    ) -> ExtractionResult:
        if source_values is None:
            source_values = {source_column or "<value>": value}
        raw_values = dict(source_values)
        lineage = [_lineage(self.target_field, type(self).__name__, raw_values)]

        surname = None
        given_name = None
        unrecognized = []
        for column, raw in raw_values.items():
            normalized = normalized_token(column)
            if normalized == "ho":
                surname = clean_optional_text(raw)
            elif normalized == "ten":
                given_name = clean_optional_text(raw)
            else:
                unrecognized.append(column)

        if unrecognized or len(raw_values) < 2:
            return ExtractionResult(
                lineage=lineage,
                issues=[
                    _issue(
                        "UNCONFIGURED_NAME_COMPONENTS",
                        "Name splitting requires explicitly mapped Ho and Ten source columns.",
                        raw_values,
                        [self.target_field],
                    )
                ],
            )

        combined = " ".join(part for part in (surname, given_name) if part) or None
        return ExtractionResult(values={self.target_field: combined}, lineage=lineage)
