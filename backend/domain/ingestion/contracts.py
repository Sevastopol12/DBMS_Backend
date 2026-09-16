"""Stable domain contracts shared by ingestion transformation stages.

These models deliberately describe source and canonical data, not database rows.
Persistence adapters are responsible for translating :class:`CanonicalRecord` to
their storage model.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, computed_field


class MappingMethod(str, Enum):
    EXACT = "EXACT"
    ALIAS = "ALIAS"
    STRUCTURAL = "STRUCTURAL"
    HEURISTIC = "HEURISTIC"
    MANUAL = "MANUAL"
    UNKNOWN = "UNKNOWN"


class ValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    MISSING = "MISSING"
    SUSPICIOUS = "SUSPICIOUS"
    UNKNOWN = "UNKNOWN"


class IssueSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class SourceRow(BaseModel):
    """An unmodified row read from an uploaded source file."""

    source_file_id: UUID
    row_number: int = Field(ge=1)
    raw_values: dict[str, Any]


class SourceDataset(BaseModel):
    """A source file represented without semantic interpretation.

    ``headers`` retains the source header order while every :class:`SourceRow`
    retains the values as they appeared in that source file.
    """

    source_file_id: UUID
    filename: str = Field(min_length=1)
    headers: list[str]
    rows: list[SourceRow] = Field(default_factory=list)


class MappingDecision(BaseModel):
    """A mapping from one or more original source columns to one semantic field."""

    source_columns: list[str] = Field(min_length=1)
    target_field: str = Field(min_length=1)
    method: MappingMethod
    confidence: float = Field(ge=0, le=1)
    reason: str | None = None


class MappingPlan(BaseModel):
    """The complete set of mapping decisions resolved for an input file."""

    source_file_id: UUID
    decisions: list[MappingDecision] = Field(default_factory=list)


class CanonicalRecord(BaseModel):
    """Normalized semantic data for one source row, independent of persistence."""

    source_row_number: int = Field(ge=1)

    ma_bhyt: str | None = None
    cccd: str | None = None
    ho_ten: str | None = None
    gioi_tinh: str | None = None
    nam_sinh: str | None = None
    sdt: str | None = None
    dia_chi: str | None = None
    phuong_xa: str | None = None
    quan_huyen: str | None = None
    tinh_thanh_pho: str | None = None
    ngay_kham: datetime | None = None
    icd_tha: str | None = None
    icd_dtd: str | None = None
    chan_doan_di_kem: str | None = None
    huyet_ap_tam_truong: str | None = None
    huyet_ap_tam_thu: str | None = None
    chi_so_duong_huyet: str | None = None
    chi_so_hba1c: str | None = None
    ghi_chu: str | None = None
    dieu_tri: str | None = None


class ValidationResult(BaseModel):
    status: ValidationStatus
    normalized_value: Any | None = None
    issue_code: str | None = None
    message: str | None = None
    severity: IssueSeverity | None = None


class QualityIssue(BaseModel):
    source_file_id: UUID
    source_row_number: int = Field(ge=1)
    source_column: str = Field(min_length=1)
    target_field: str = Field(min_length=1)
    raw_value: Any | None = None
    normalized_value: Any | None = None
    issue_code: str
    severity: IssueSeverity
    message: str


class TransformResult(BaseModel):
    """Output of transforming one source file.

    ``accepted_rows`` are the only rows eligible for persistence. Rejected source
    rows and all quality issues remain available for reporting without making a
    persistence model part of the transformation contract.
    """

    source_file_id: UUID
    accepted_rows: list[CanonicalRecord] = Field(default_factory=list)
    rejected_rows: list[SourceRow] = Field(default_factory=list)
    quality_issues: list[QualityIssue] = Field(default_factory=list)

    @computed_field
    @property
    def accepted_row_count(self) -> int:
        return len(self.accepted_rows)

    @computed_field
    @property
    def rejected_row_count(self) -> int:
        return len(self.rejected_rows)
