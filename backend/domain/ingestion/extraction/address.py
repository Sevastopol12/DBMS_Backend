from typing import Any, Sequence, Mapping
from .base import ValueExtractor
from .extractors import _raw, _lineage, _issue, ExtractionResult
from backend.domain.ingestion.normalization import clean_optional_text


class AddressExtractor(ValueExtractor):
    """Preserve full addresses or join caller-identified address components."""

    COMPONENT_FIELDS = ("phuong_xa", "quan_huyen", "tinh_thanh_pho")

    def __init__(
        self,
        target_field: str = "dia_chi",
        *,
        component_fields: Sequence[str] = COMPONENT_FIELDS,
    ) -> None:
        self.target_field, self.component_fields = target_field, tuple(component_fields)

    def extract(
        self,
        value: Any = None,
        *,
        source_column: str | None = None,
        source_values: Mapping[str, Any] | None = None,
        row: Mapping[str, Any] | None = None,
    ) -> ExtractionResult:
        raw_values = _raw(source_column, value, source_values)
        targets = (
            (self.target_field, *self.component_fields)
            if source_values is not None
            else (self.target_field,)
        )
        lineage = [
            _lineage(target, type(self).__name__, raw_values) for target in targets
        ]
        if source_values is None:
            return ExtractionResult(
                values={self.target_field: clean_optional_text(value)}, lineage=lineage
            )
        unknown = set(source_values) - set(self.component_fields)
        if unknown:
            return ExtractionResult(
                lineage=lineage,
                issues=[
                    _issue(
                        "UNCONFIGURED_ADDRESS_COMPONENT",
                        "Address component names must be explicitly supplied as canonical component fields.",
                        raw_values,
                        targets,
                    )
                ],
            )
        components = {
            field: clean_optional_text(source_values.get(field))
            for field in self.component_fields
            if field in source_values
        }
        if not components:
            return ExtractionResult(
                lineage=lineage,
                issues=[
                    _issue(
                        "AMBIGUOUS_ADDRESS_COMPONENTS",
                        "No configured address components were supplied.",
                        raw_values,
                        targets,
                    )
                ],
            )
        values = dict(components)
        values[self.target_field] = (
            ", ".join(item for item in components.values() if item) or None
        )
        return ExtractionResult(values=values, lineage=lineage)
