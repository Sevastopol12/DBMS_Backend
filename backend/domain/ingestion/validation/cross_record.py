"""Row and cross-record validation, deliberately separate from field validators."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable
from uuid import UUID

from pydantic import BaseModel, Field

from backend.domain.ingestion.contracts import (
    CanonicalRecord,
    IssueSeverity,
    QualityIssue,
    ValidationStatus,
)
from backend.domain.ingestion.validation.validators import validate_bhyt, validate_cccd
from backend.domain.ingestion.header import normalize


class RowValidationContext(BaseModel):
    source_file_id: UUID
    row_number: int
    raw_values: dict[str, Any]
    identifier_sources: dict[str, list[str]] = Field(default_factory=dict)


class CrossRecordValidationContext(BaseModel):
    source_file_id: UUID
    records: list[CanonicalRecord]
    source_columns: dict[int, dict[str, str]] = Field(default_factory=dict)
    identity_key_fields: tuple[str, ...] = ()


def _issue(
    context: RowValidationContext,
    *,
    source_column: str,
    target_field: str,
    raw_value: Any,
    normalized_value: Any,
    code: str,
    message: str,
    related_rows: Iterable[int] = (),
    related_values: Iterable[str] = (),
) -> QualityIssue:
    return QualityIssue(
        source_file_id=context.source_file_id,
        source_row_number=context.row_number,
        source_column=source_column,
        normalized_column=normalize(source_column),
        target_field=target_field,
        raw_value=raw_value,
        normalized_value=normalized_value,
        issue_code=code,
        severity=IssueSeverity.ERROR,
        message=message,
        related_row_numbers=sorted(set(related_rows)),
        related_identifier_values=sorted(set(related_values)),
    )


def validate_identifier_sources(context: RowValidationContext) -> list[QualityIssue]:
    """Report differing non-empty normalized identifier values in one source row."""
    issues: list[QualityIssue] = []
    for field, columns in context.identifier_sources.items():
        validator = validate_cccd if field == "cccd" else validate_bhyt
        values: list[tuple[str, Any, str]] = []
        for column in columns:
            raw = context.raw_values.get(column)
            result = validator(raw)
            if (
                result.status is ValidationStatus.VALID
                and result.normalized_value is not None
            ):
                values.append((column, raw, str(result.normalized_value)))
        distinct = sorted({value for _, _, value in values})
        if len(distinct) > 1:
            for column, raw, normalized in values:
                issues.append(
                    _issue(
                        context,
                        source_column=column,
                        target_field=field,
                        raw_value=raw,
                        normalized_value=normalized,
                        code=f"CONFLICTING_{field.upper()}_SOURCE_VALUES",
                        message=f"Mapped {field} columns contain different normalized identifier values.",
                        related_values=distinct,
                    )
                )
    return issues


def validate_cccd_cross_fields(
    context: RowValidationContext, record: CanonicalRecord, source_column: str
) -> list[QualityIssue]:
    """Compare valid CCCD encoding to explicitly normalized row fields only."""
    result = validate_cccd(record.cccd)
    if result.status is not ValidationStatus.VALID:
        return []
    issues: list[QualityIssue] = []
    encoded_gender = result.metadata["encoded_gender"]
    encoded_year = result.metadata["encoded_birth_year"]
    if record.gioi_tinh is not None and record.gioi_tinh != encoded_gender:
        issues.append(
            _issue(
                context,
                source_column=source_column,
                target_field="cccd",
                raw_value=record.cccd,
                normalized_value=record.cccd,
                code="CCCD_GENDER_MISMATCH",
                message="CCCD encoded gender does not match the normalized gender field.",
            )
        )
    # CanonicalRecord has a documented birth-year field, not a full date of birth.
    if record.nam_sinh is not None and record.nam_sinh != str(encoded_year):
        issues.append(
            _issue(
                context,
                source_column=source_column,
                target_field="cccd",
                raw_value=record.cccd,
                normalized_value=record.cccd,
                code="CCCD_BIRTH_YEAR_MISMATCH",
                message="CCCD encoded birth year does not match the normalized birth-year field.",
            )
        )
    return issues


def validate_cross_records(context: CrossRecordValidationContext) -> list[QualityIssue]:
    """Report duplicates and optional reliable-key identifier conflicts in memory."""
    issues: list[QualityIssue] = []
    for field in ("cccd", "ma_bhyt"):
        grouped: dict[str, list[CanonicalRecord]] = defaultdict(list)
        for record in context.records:
            value = getattr(record, field)
            if value is not None:
                grouped[value].append(record)
        for value, records in grouped.items():
            if len(records) < 2:
                continue
            rows = [record.source_row_number for record in records]
            for record in records:
                source = context.source_columns.get(record.source_row_number, {}).get(
                    field, "<unmapped>"
                )
                issues.append(
                    QualityIssue(
                        source_file_id=context.source_file_id,
                        source_row_number=record.source_row_number,
                        source_column=source,
                        normalized_column=normalize(source),
                        target_field=field,
                        raw_value=value,
                        normalized_value=value,
                        issue_code=f"DUPLICATE_{field.upper()}",
                        severity=IssueSeverity.ERROR,
                        message=f"Duplicate {field} value occurs in source rows {', '.join(map(str, sorted(rows)))}.",
                        related_row_numbers=sorted(rows),
                        related_identifier_values=[value],
                    )
                )
    if not context.identity_key_fields:
        return issues
    by_identity: dict[tuple[str, ...], list[CanonicalRecord]] = defaultdict(list)
    for record in context.records:
        key = tuple(
            str(getattr(record, field) or "") for field in context.identity_key_fields
        )
        if all(key):
            by_identity[key].append(record)
    for key, records in by_identity.items():
        for field in ("cccd", "ma_bhyt"):
            values = sorted(
                {
                    getattr(record, field)
                    for record in records
                    if getattr(record, field) is not None
                }
            )
            if len(values) < 2:
                continue
            rows = sorted(
                record.source_row_number
                for record in records
                if getattr(record, field) is not None
            )
            for record in records:
                value = getattr(record, field)
                if value is None:
                    continue
                source = context.source_columns.get(record.source_row_number, {}).get(
                    field, "<unmapped>"
                )
                issues.append(
                    QualityIssue(
                        source_file_id=context.source_file_id,
                        source_row_number=record.source_row_number,
                        source_column=source,
                        normalized_column=normalize(source),
                        target_field=field,
                        raw_value=value,
                        normalized_value=value,
                        issue_code=f"CONFLICTING_{field.upper()}_FOR_IDENTITY",
                        severity=IssueSeverity.ERROR,
                        message=f"Reliable identity key {key!r} is associated with conflicting {field} values.",
                        related_row_numbers=rows,
                        related_identifier_values=values,
                    )
                )
    return issues
