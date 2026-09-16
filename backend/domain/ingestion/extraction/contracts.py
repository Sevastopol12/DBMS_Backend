"""Contracts for value extraction, separate from semantic mapping."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.domain.ingestion.contracts import IssueSeverity


class ExtractionIssue(BaseModel):
    """An explicit non-fatal extraction outcome with raw-value provenance."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: IssueSeverity = IssueSeverity.ERROR
    source_columns: list[str] = Field(default_factory=list)
    target_fields: list[str] = Field(default_factory=list)
    raw_values: dict[str, Any] = Field(default_factory=dict)


class ExtractedValueLineage(BaseModel):
    """Records exactly which raw values produced a canonical field value."""

    target_field: str = Field(min_length=1)
    extractor: str = Field(min_length=1)
    source_columns: list[str] = Field(default_factory=list)
    raw_values: dict[str, Any] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    """Canonical values plus source lineage and any explicit extraction issues."""

    values: dict[str, Any] = Field(default_factory=dict)
    lineage: list[ExtractedValueLineage] = Field(default_factory=list)
    issues: list[ExtractionIssue] = Field(default_factory=list)
