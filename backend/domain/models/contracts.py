from __future__ import annotations

from enum import Enum
from datetime import date
from typing import Any, Iterable
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from .canonical import (
    ACCEPTANCE_FIELDS,
    CANONICAL_FIELD_NAMES,
    CANONICAL_FIELD_SET,
)
from .transform import ReportRow


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
    def calculate_statistics(self) -> "MappingPlan":
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

    @property
    def target_fields(self) -> list[str]:
        return list(self.field_plans)

    @classmethod
    def from_field_plans(
        cls,
        field_plans: Iterable[FieldPlan],
        *,
        unmapped_headers: Iterable[str] = (),
        ambiguous_headers: Iterable[str] = (),
    ) -> "MappingPlan":
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


class RuleMode(str, Enum):
    OFF = "OFF"
    FLAG = "FLAG"
    GATE = "GATE"


class ValidationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plausibility: RuleMode = RuleMode.GATE
    cross_field: RuleMode = RuleMode.FLAG
    cccd_structure: RuleMode = RuleMode.FLAG
    bhxh_era: RuleMode = RuleMode.FLAG
    reference_date: date | None = None


class RowDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_FLAGS = "ACCEPTED_WITH_FLAGS"
    REJECTED = "REJECTED"


class RowIssueRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_row_number: int = Field(ge=2)
    disposition: RowDisposition
    issue_codes: list[str]


class FieldQuality(BaseModel):
    valid: int = 0
    missing: int = 0
    invalid: int = 0
    suspicious: int = 0

    @computed_field
    @property
    def valid_rate(self) -> float:
        total = self.valid + self.missing + self.invalid + self.suspicious
        return self.valid / total if total else 0.0


class QualityReport(BaseModel):
    """Safe aggregate report; it intentionally contains no raw row values."""

    file_id: UUID | None = None
    decision: FileDecision = FileDecision.ACCEPTED
    processing_stage: ProcessingStage = ProcessingStage.COMPLETED
    total_target_fields: int = len(CANONICAL_FIELD_NAMES)
    mapped_target_fields: int = 0
    coverage_ratio: float = 0.0
    unmapped_headers: list[str] = Field(default_factory=list)
    ambiguous_headers: list[str] = Field(default_factory=list)
    total_rows: int = 0
    accepted_rows: int = 0
    flagged_rows: int = 0
    rejected_rows: int = 0
    field_quality: dict[str, FieldQuality] = Field(default_factory=dict)
    issue_code_counts: dict[str, int] = Field(default_factory=dict)
    safe_error_samples: list[dict[str, str | int]] = Field(default_factory=list)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @computed_field
    @property
    def valid_rates(self) -> dict[str, float]:
        return {
            field: quality.valid_rate for field, quality in self.field_quality.items()
        }


class FileAcceptancePolicy(BaseModel):
    """Structural and explicitly configured quality gates for one source file.

    Mapping coverage is the only file-level acceptance gate.  Validation
    remains diagnostic; row acceptance is determined by ``ACCEPTANCE_FIELDS``.

    The legacy quality-policy fields remain in the contract for callers that
    still send them, but they do not alter acceptance semantics.
    """

    min_mapping_coverage: float = 0.5
    required_fields: tuple[str, ...] = ACCEPTANCE_FIELDS
    min_valid_rate: float = 0.0
    min_valid_rates: dict[str, float] = Field(default_factory=dict)
    reject_if_all_rows_invalid: bool = False
    validation: ValidationPolicy = Field(default_factory=ValidationPolicy)

    @field_validator("min_mapping_coverage", "min_valid_rate")
    @classmethod
    def validate_rate(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("rate thresholds must be between 0 and 1")
        return value

    @field_validator("min_valid_rates")
    @classmethod
    def validate_rates(cls, value: dict[str, float]) -> dict[str, float]:
        for field, rate in value.items():
            if field not in CANONICAL_FIELD_SET:
                raise ValueError(f"Unknown canonical field: {field}")
            if not 0 <= rate <= 1:
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

    def row_rejection_reasons(
        self, report: QualityReport, *, accepted_rows: int, total_rows: int
    ) -> list[str]:
        """Keep validation diagnostics separate from production acceptance."""
        return []


class TransformResult(BaseModel):
    file_id: UUID
    accepted_rows: list[ReportRow] = Field(default_factory=list)
    accepted_row_numbers: list[int] = Field(default_factory=list)
    accepted_row_count: int = 0
    rejected_row_count: int = 0
    quality_report: QualityReport
    review_records: list[RowIssueRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def synchronize_counts(self) -> "TransformResult":
        supplied_count = "accepted_row_count" in self.model_fields_set
        if supplied_count and self.accepted_row_count != len(self.accepted_rows):
            raise ValueError("accepted_row_count must match accepted_rows")
        self.accepted_row_count = len(self.accepted_rows)
        if self.accepted_rows and not self.accepted_row_numbers:
            raise ValueError(
                "accepted_row_numbers are required when accepted_rows are present"
            )
        if len(self.accepted_row_numbers) != self.accepted_row_count:
            raise ValueError("accepted_row_numbers must match accepted_rows")
        if any(
            not isinstance(number, int) or number < 2
            for number in self.accepted_row_numbers
        ):
            raise ValueError("accepted_row_numbers must be source data row numbers")
        if len(set(self.accepted_row_numbers)) != len(self.accepted_row_numbers):
            raise ValueError("accepted_row_numbers must be unique")
        review_row_numbers = [
            record.source_row_number for record in self.review_records
        ]
        if any(
            record.disposition is RowDisposition.ACCEPTED
            for record in self.review_records
        ):
            raise ValueError("review_records cannot contain clean accepted rows")
        if len(set(review_row_numbers)) != len(review_row_numbers):
            raise ValueError("review_records row numbers must be unique")
        rejected_row_numbers = {
            record.source_row_number
            for record in self.review_records
            if record.disposition is RowDisposition.REJECTED
        }
        if rejected_row_numbers.intersection(self.accepted_row_numbers):
            raise ValueError("rejected review rows cannot be accepted rows")
        return self


def safe_issue_sample(row_number: int, issue_code: str) -> dict[str, str | int]:
    return {"row_number": row_number, "issue_code": issue_code}


__all__ = [
    "FieldPlan",
    "FileAcceptancePolicy",
    "FileDecision",
    "FieldQuality",
    "MappingOperation",
    "MappingPlan",
    "ProcessingStage",
    "QualityReport",
    "RowDisposition",
    "RowIssueRecord",
    "RuleMode",
    "TransformResult",
    "ValidationPolicy",
    "safe_issue_sample",
]
