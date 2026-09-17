"""Domain contracts for ingestion and transformation boundaries."""

from .contracts import (
    CanonicalRecord,
    IssueSeverity,
    MappingDecision,
    MappingOperation,
    MappingMethod,
    MappingPlan,
    QualityIssue,
    SourceDataset,
    SourceRow,
    TransformResult,
    ValidationResult,
    ValidationStatus,
)
from .pipeline import TransformationPipeline

__all__ = [
    "CanonicalRecord",
    "IssueSeverity",
    "MappingDecision",
    "MappingOperation",
    "MappingMethod",
    "MappingPlan",
    "QualityIssue",
    "SourceDataset",
    "SourceRow",
    "TransformResult",
    "TransformationPipeline",
    "ValidationResult",
    "ValidationStatus",
]
