import re
from datetime import date, datetime
from typing import Any, Mapping
from .base import ValueExtractor
from .extractors import _raw, _lineage, _issue, ExtractionResult
from backend.domain.ingestion.normalization import clean_optional_text


def _matches_date(value: str, format_: str) -> bool:
    try:
        datetime.strptime(value, format_)
    except ValueError:
        return False
    return True


class DateExtractor(ValueExtractor):
    """Parse only ISO dates/years by default; slash dates require a convention."""

    def __init__(
        self, target_field: str, *, slash_convention: str | None = None
    ) -> None:
        if slash_convention not in {None, "DAY_FIRST", "MONTH_FIRST"}:
            raise ValueError("slash_convention must be DAY_FIRST, MONTH_FIRST, or None")
        self.target_field, self.slash_convention = target_field, slash_convention

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
        if source_values is not None and len(source_values) != 1:
            return ExtractionResult(
                lineage=lineage,
                issues=[
                    _issue(
                        "AMBIGUOUS_SOURCE_VALUES",
                        "Date extraction requires one source value.",
                        raw_values,
                        [self.target_field],
                    )
                ],
            )
        raw_value = next(iter(raw_values.values()))
        if isinstance(raw_value, datetime):
            parsed: date | None = raw_value.date()
        elif isinstance(raw_value, date):
            parsed = raw_value
        else:
            text = clean_optional_text(raw_value)
            if text is None:
                return ExtractionResult(
                    values={self.target_field: None}, lineage=lineage
                )
            if re.fullmatch(r"\d{4}", text):
                return ExtractionResult(
                    values={self.target_field: text}, lineage=lineage
                )
            formats = ["%Y-%m-%d"]
            if "/" in text and self.slash_convention:
                formats.append(
                    "%d/%m/%Y" if self.slash_convention == "DAY_FIRST" else "%m/%d/%Y"
                )
            try:
                parsed = next(
                    datetime.strptime(text, fmt).date()
                    for fmt in formats
                    if _matches_date(text, fmt)
                )
            except StopIteration:
                slash_day_month_shape = bool(
                    re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", text)
                )
                code = (
                    "AMBIGUOUS_DATE"
                    if slash_day_month_shape and self.slash_convention is None
                    else "MALFORMED_DATE"
                )
                message = (
                    "Slash-formatted dates need an explicit convention."
                    if code == "AMBIGUOUS_DATE"
                    else "Date does not match an explicitly supported format."
                )
                return ExtractionResult(
                    lineage=lineage,
                    issues=[_issue(code, message, raw_values, [self.target_field])],
                )
        if self.target_field == "nam_sinh":
            return ExtractionResult(
                values={self.target_field: str(parsed.year)}, lineage=lineage
            )
        return ExtractionResult(values={self.target_field: parsed}, lineage=lineage)
