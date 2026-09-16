"""Structured quality reporting and explicit row acceptance policy."""

from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID

from pydantic import BaseModel, Field

from backend.domain.ingestion.contracts import (
    IssueSeverity,
    QualityIssue,
    ValidationResult,
    ValidationStatus,
)


class FieldQuality(BaseModel):
    raw_value: Any | None = None
    normalized_value: Any | None = None
    validation: ValidationResult


class RowQualityPolicy(BaseModel):
    """Only configured error statuses reject a row; validators never do so."""

    rejecting_statuses: set[ValidationStatus] = Field(
        default_factory=lambda: {ValidationStatus.INVALID, ValidationStatus.MISSING}
    )
    rejecting_severities: set[IssueSeverity] = Field(
        default_factory=lambda: {IssueSeverity.ERROR}
    )

    def rejects(self, results: Iterable[ValidationResult]) -> bool:
        return any(
            result.status in self.rejecting_statuses
            or result.severity in self.rejecting_severities
            for result in results
        )


def quality_issue(
    *,
    source_file_id: UUID,
    source_row_number: int,
    source_column: str,
    normalized_column: str | None = None,
    target_field: str,
    raw_value: Any,
    result: ValidationResult,
) -> QualityIssue | None:
    """Translate a non-valid field result into traceable reporting data."""
    if result.status is ValidationStatus.VALID:
        return None
    return QualityIssue(
        source_file_id=source_file_id,
        source_row_number=source_row_number,
        source_column=source_column,
        normalized_column=normalized_column,
        target_field=target_field,
        raw_value=raw_value,
        normalized_value=result.normalized_value,
        issue_code=result.issue_code or result.status.value,
        severity=result.severity or IssueSeverity.WARNING,
        message=result.message or result.status.value,
    )
