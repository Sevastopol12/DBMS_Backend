from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from backend.database.canonical import (
    ACCEPTANCE_FIELDS,
    CANONICAL_FIELD_NAMES,
    CANONICAL_FIELD_SET,
)
from backend.timezone import VIETNAM_TZ, ensure_vietnam_aware

type SourceCellValue = object | None
type SourceRow = dict[str, SourceCellValue]


class ReportRow(BaseModel):
    ma_bhyt: str | None = None
    cccd: str | None = None

    # Demographic
    ho_ten: str | None = None
    gioi_tinh: str | None = None
    nam_sinh: str | None = None
    sdt: str | None = None

    # Address
    dia_chi: str | None = None

    ngay_kham: datetime | None = None

    # Clinical metrics

    # Icd hypertension
    icd_tha: str | None = None
    # Icd diabetes
    icd_dtd: str | None = None
    chan_doan_di_kem: str | None = None
    # Diastolic blood pressure
    huyet_ap_tam_truong: str | None = None
    # Systolic blood pressure
    huyet_ap_tam_thu: str | None = None

    chi_so_duong_huyet: str | None = None
    chi_so_hba1c: str | None = None

    ghi_chu: str | None = None
    dieu_tri: str | None = None

    @field_validator("ngay_kham", mode="before")
    @classmethod
    def parse_visit_date(cls, value: object) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            # Naive input is Vietnam local time; truncate to whole seconds
            # per D-01 before grouping and persistence.
            return ensure_vietnam_aware(value).replace(microsecond=0)
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time(), tzinfo=VIETNAM_TZ)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return ensure_vietnam_aware(datetime.fromisoformat(text)).replace(
                    microsecond=0
                )
            except ValueError:
                pass
        raise ValueError("ngay_kham must be an ISO date or datetime")


class ColumnMap(BaseModel):
    original_name: str
    normalized_name: str
    mapping_target: str | None


class CacheSource(str, Enum):
    DIRECT = "DIRECT"
    DYNAMIC = "DYNAMIC"


class HeaderMapValue(BaseModel):
    value: str | None
    cache_key: CacheSource


class SourceDataset(BaseModel):
    """Raw tabular data with rows keyed by the original header names."""

    source_file_id: UUID
    filename: str
    headers: list[str]
    rows: list[SourceRow] = Field(default_factory=list)


class FileStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCEED = "SUCCEED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class MappingOperation(str, Enum):
    DIRECT = "DIRECT"
    COALESCE = "COALESCE"
    CONCAT = "CONCAT"
    SPLIT = "SPLIT"
    SPLIT_BLOOD_PRESSURE = "SPLIT_BLOOD_PRESSURE"
    SPLIT_ICD = "SPLIT_ICD"
    DERIVE_GENDER = "DERIVE_GENDER"
    DERIVE_GENDER_FROM_FLAGS = "DERIVE_GENDER_FROM_FLAGS"
    PARSE_BIRTH_DATE = "PARSE_BIRTH_DATE"
    PARSE_IDENTIFIER = "PARSE_IDENTIFIER"


class FieldPlan(BaseModel):
    """An executable mapping for one canonical target field."""

    model_config = ConfigDict(extra="forbid")

    target_field: str
    source_columns: list[str] = Field(default_factory=list)
    operation: MappingOperation = MappingOperation.DIRECT
    confidence: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target_field")
    @classmethod
    def validate_target_field(cls, value: str) -> str:
        if value not in CANONICAL_FIELD_SET:
            raise ValueError(f"Unknown canonical target field: {value}")
        return value

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float | None) -> float | None:
        if value is not None and not 0 <= value <= 100:
            raise ValueError("confidence must be between 0 and 100")
        return value

    @property
    def executable(self) -> bool:
        return bool(self.source_columns)


class MappingPlan(BaseModel):
    """File-level mapping result and coverage statistics."""

    model_config = ConfigDict(extra="forbid")

    field_plans: dict[str, FieldPlan] = Field(default_factory=dict)
    unmapped_headers: list[str] = Field(default_factory=list)
    ambiguous_headers: list[str] = Field(default_factory=list)
    total_target_fields: int = len(CANONICAL_FIELD_NAMES)
    mapped_target_fields: int = 0
    coverage_ratio: float = 0.0

    @model_validator(mode="after")
    def calculate_statistics(self) -> MappingPlan:
        invalid = set(self.field_plans) - CANONICAL_FIELD_SET
        if invalid:
            raise ValueError(f"Unknown mapping targets: {sorted(invalid)}")
        self.total_target_fields = len(CANONICAL_FIELD_NAMES)
        self.mapped_target_fields = sum(
            1 for plan in self.field_plans.values() if plan.executable
        )
        self.coverage_ratio = (
            self.mapped_target_fields / self.total_target_fields
            if self.total_target_fields
            else 1.0
        )
        return self

    @classmethod
    def from_field_plans(
        cls,
        field_plans: Iterable[FieldPlan],
        *,
        unmapped_headers: Iterable[str] = (),
        ambiguous_headers: Iterable[str] = (),
    ) -> MappingPlan:
        plans = {plan.target_field: plan for plan in field_plans}
        return cls(
            field_plans=plans,
            unmapped_headers=list(dict.fromkeys(unmapped_headers)),
            ambiguous_headers=list(dict.fromkeys(ambiguous_headers)),
        )


class ProcessingStage(str, Enum):
    STRUCTURAL = "structural"
    MAPPING = "mapping"
    EXTRACTION = "extraction"
    NORMALIZATION = "normalization"
    VALIDATION = "validation"
    POLICY = "policy"
    PERSISTENCE = "persistence"
    COMPLETED = "completed"
    FAILED = "failed"


class FileDecision(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


class ValidationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plausibility_enabled: bool = True
    reference_date: date | None = None


class RowDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DuplicateRole(str, Enum):
    NONE = "NONE"
    PRIMARY = "PRIMARY"
    MERGED = "MERGED"


class RowDecision(BaseModel):
    """One per REJECTED row and per MERGED row (WP-01 emits REJECTED only)."""

    model_config = ConfigDict(extra="forbid")

    source_row_number: int = Field(ge=2)
    disposition: RowDisposition
    duplicate_role: DuplicateRole = DuplicateRole.NONE
    merged_into_row: int | None = None
    group_row_numbers: list[int] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)


class AcceptedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: ReportRow
    primary_row_number: int = Field(ge=2)
    contributing_row_numbers: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_primary_is_group_head(self) -> AcceptedRecord:
        if not self.contributing_row_numbers:
            raise ValueError("contributing_row_numbers must not be empty")
        if self.primary_row_number != self.contributing_row_numbers[0]:
            raise ValueError("primary_row_number must be the first contributing row")
        return self


class FieldQuality(BaseModel):
    valid: int = 0
    missing: int = 0
    invalid: int = 0

    @computed_field
    @property
    def valid_rate(self) -> float:
        total = self.valid + self.missing + self.invalid
        return self.valid / total if total else 0.0


class QualityReport(BaseModel):
    """Safe aggregate report; it intentionally contains no raw row values."""

    file_id: UUID | None = None
    facility_id: UUID | None = None
    decision: FileDecision = FileDecision.ACCEPTED
    processing_stage: ProcessingStage = ProcessingStage.COMPLETED
    total_target_fields: int = len(CANONICAL_FIELD_NAMES)
    mapped_target_fields: int = 0
    coverage_ratio: float = 0.0
    unmapped_headers: list[str] = Field(default_factory=list)
    ambiguous_headers: list[str] = Field(default_factory=list)
    total_rows: int = 0
    accepted_rows: int = 0
    rejected_rows: int = 0
    ignored_duplicate_row_count: int = 0
    quality_schema_version: int = 2
    field_quality: dict[str, FieldQuality] = Field(default_factory=dict)
    issue_code_counts: dict[str, int] = Field(default_factory=dict)
    safe_error_samples: list[dict[str, str | int]] = Field(default_factory=list)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @property
    def counts_balanced(self) -> bool:
        return (
            self.accepted_rows + self.rejected_rows + self.ignored_duplicate_row_count
            == self.total_rows
        )

    @computed_field
    @property
    def valid_rates(self) -> dict[str, float]:
        return {
            field: quality.valid_rate for field, quality in self.field_quality.items()
        }


class FileAcceptancePolicy(BaseModel):
    """File-level acceptance gate for one source file.

    Mapping coverage is the only file-level acceptance gate. Row acceptance
    is determined by ``ACCEPTANCE_FIELDS`` in the engine.
    """

    min_mapping_coverage: float = 0.5
    required_fields: tuple[str, ...] = ACCEPTANCE_FIELDS
    validation: ValidationPolicy = Field(default_factory=ValidationPolicy)

    @field_validator("min_mapping_coverage")
    @classmethod
    def validate_rate(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("rate thresholds must be between 0 and 1")
        return value

    @field_validator("required_fields")
    @classmethod
    def validate_required_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = set(value) - CANONICAL_FIELD_SET
        if unknown:
            raise ValueError(f"Unknown required fields: {sorted(unknown)}")
        return tuple(dict.fromkeys(value))

    def mapping_rejection_reasons(self, plan: MappingPlan) -> list[str]:
        reasons: list[str] = []
        if plan.coverage_ratio < self.min_mapping_coverage:
            reasons.append("MAPPING_COVERAGE_BELOW_MINIMUM")
        # A missing target mapping is a row-quality problem.  It must not
        # turn into a file rejection when the structural mapping gate passes.
        return reasons


class TransformResult(BaseModel):
    file_id: UUID
    accepted_records: list[AcceptedRecord] = Field(default_factory=list)
    decisions: list[RowDecision] = Field(default_factory=list)
    accepted_row_count: int = 0
    rejected_row_count: int = 0
    ignored_duplicate_row_count: int = 0
    quality_report: QualityReport
    source: SourceDataset | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def synchronize_counts(self) -> TransformResult:
        if self.accepted_row_count != len(self.accepted_records):
            raise ValueError("accepted_row_count must match accepted_records")
        decision_rows = [decision.source_row_number for decision in self.decisions]
        if len(set(decision_rows)) != len(decision_rows):
            raise ValueError("decision row numbers must be unique")
        accepted_rows = {record.primary_row_number for record in self.accepted_records}
        if accepted_rows.intersection(decision_rows):
            raise ValueError("a row cannot be both accepted and decided")
        return self


def safe_issue_sample(row_number: int, issue_code: str) -> dict[str, str | int]:
    return {"row_number": row_number, "issue_code": issue_code}


__all__ = [
    "AcceptedRecord",
    "CacheSource",
    "ColumnMap",
    "DuplicateRole",
    "FieldPlan",
    "FieldQuality",
    "FileAcceptancePolicy",
    "FileDecision",
    "FileStatus",
    "HeaderMapValue",
    "MappingOperation",
    "MappingPlan",
    "ProcessingStage",
    "QualityReport",
    "ReportRow",
    "RowDecision",
    "RowDisposition",
    "SourceCellValue",
    "SourceDataset",
    "SourceRow",
    "TransformResult",
    "ValidationPolicy",
    "safe_issue_sample",
]
