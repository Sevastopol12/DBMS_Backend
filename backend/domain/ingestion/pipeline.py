"""Application-independent, deterministic tabular transformation pipeline."""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Iterable
from hashlib import sha256
from uuid import UUID

from backend.domain.ingestion.contracts import (
    CanonicalRecord,
    IssueSeverity,
    MappingMethod,
    MappingOperation,
    MappingPlan,
    QualityIssue,
    TransformResult,
    ValidationResult,
    ValidationStatus,
)
from backend.domain.ingestion.extraction import (
    BloodPressureExtractor,
    DateExtractor,
    DirectExtractor,
    GenderExtractor,
    ICDExtractor,
    SplitNameExtractor,
)
from backend.domain.ingestion.mapping import resolve_headers
from backend.domain.ingestion.header import normalize
from backend.domain.ingestion.quality import RowQualityPolicy, quality_issue
from backend.domain.ingestion.reader import read_source_dataset
from backend.domain.ingestion.validation import (
    CrossRecordValidationContext,
    RowValidationContext,
    validate_bhyt,
    validate_blood_pressure,
    validate_cccd,
    validate_date,
    validate_gender,
    validate_icd,
    validate_cccd_cross_fields,
    validate_cross_records,
    validate_identifier_sources,
)
from backend.domain.ingestion.versions import MAPPING_VERSION, TRANSFORM_VERSION


_CANONICAL_FIELDS = set(CanonicalRecord.model_fields) - {"source_row_number"}
_VALIDATORS: dict[str, Callable[[Any], ValidationResult]] = {
    "cccd": validate_cccd,
    "ma_bhyt": validate_bhyt,
    "gioi_tinh": validate_gender,
    "ngay_kham": validate_date,
    "icd_tha": validate_icd,
    "icd_dtd": validate_icd,
}


class TransformationPipeline:
    """Compose reader, mapping, extraction, normalization and quality stages.

    The object has no infrastructure dependencies.  ``source_file_id`` is an
    explicit process argument so callers can retain their persistence identity.
    When omitted, it is deterministically derived from the input content.
    """

    def __init__(
        self,
        *,
        mapping_version: str = MAPPING_VERSION,
        transform_version: str = TRANSFORM_VERSION,
        required_fields: Iterable[str] = (),
        identity_key_fields: Iterable[str] = (),
        row_quality_policy: RowQualityPolicy | None = None,
    ) -> None:
        self.mapping_version = mapping_version
        self.transform_version = transform_version
        # Preserve caller order so quality issue ordering is stable as well as
        # the underlying transformation values.  ``dict`` also removes an
        # accidental duplicate requirement without relying on hash ordering.
        self.required_fields = tuple(dict.fromkeys(required_fields))
        self.identity_key_fields = tuple(identity_key_fields)
        self.row_quality_policy = row_quality_policy or RowQualityPolicy()

    def process(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        source_file_id: UUID,
        mappings: dict[str, str] | None = None,
    ) -> TransformResult:

        dataset = read_source_dataset(file_bytes, filename, source_file_id)

        report = resolve_headers(dataset.headers, mappings)

        plan = MappingPlan(
            source_file_id=source_file_id,
            operations=list(report.operations),
            decisions=[item.decision for item in report.decisions],
        )

        eligible, schema_issues = self._eligible_operations(
            report.operations, source_file_id
        )
        eligible_decisions = [
            decision
            for decision in report.decisions
            if decision.operation_id in {operation.operation_id for operation in eligible}
        ]

        accepted: list[CanonicalRecord] = []
        rejected = []
        issues: list[QualityIssue] = []
        source_columns_by_row: dict[int, dict[str, str]] = {}

        for row in dataset.rows:
            row_issues = list(schema_issues(row.row_number, row.raw_values))

            identifier_validation_issues: list[QualityIssue] = []
            identifier_sources = {
                field: [
                    source
                    for operation in eligible
                    if field in operation.target_fields
                    for source in operation.source_columns
                ]
                for field in ("cccd", "ma_bhyt")
            }

            row_context = RowValidationContext(
                source_file_id=source_file_id,
                row_number=row.row_number,
                raw_values=row.raw_values,
                identifier_sources=identifier_sources,
            )

            identifier_validation_issues.extend(
                validate_identifier_sources(row_context)
            )
            row_issues.extend(identifier_validation_issues)

            values: dict[str, Any] = {}
            results: dict[str, ValidationResult] = {}

            for operation in eligible:
                extraction = self._extract(operation, row.raw_values)

                for field, extracted_value in extraction.values.items():
                    # Multiple mapped identifier columns are retained for row-level
                    # comparison.  Header order remains deterministic; conflicts
                    # are reported by the identifier validator.
                    if field not in values or field not in {"cccd", "ma_bhyt"}:
                        values[field] = extracted_value

                for extraction_issue in extraction.issues:
                    for target in extraction_issue.target_fields or operation.target_fields:
                        source = (
                            extraction_issue.source_columns[0]
                            if extraction_issue.source_columns
                            else operation.source_columns[0]
                        )
                        raw_value = extraction_issue.raw_values.get(source)
                        result = ValidationResult(
                            status=ValidationStatus.INVALID,
                            normalized_value=None,
                            issue_code=extraction_issue.code,
                            message=extraction_issue.message,
                            severity=extraction_issue.severity,
                        )
                        results[target] = result
                        issue = quality_issue(
                            source_file_id=source_file_id,
                            source_row_number=row.row_number,
                            source_column=source,
                            normalized_column=self._normalized_source_for(
                                source, eligible_decisions
                            ),
                            target_field=target,
                            raw_value=raw_value,
                            result=result,
                        )
                        if issue:
                            row_issues.append(issue)

            validated_fields: set[str] = set()
            for field, value in list(values.items()):
                if field in validated_fields:
                    continue
                if field in {"huyet_ap_tam_thu", "huyet_ap_tam_truong"}:
                    validated_fields.update({"huyet_ap_tam_thu", "huyet_ap_tam_truong"})
                result = self._validate(field, value, values)
                if result is None:
                    continue
                if field in {"huyet_ap_tam_thu", "huyet_ap_tam_truong"} and isinstance(
                    result.normalized_value, dict
                ):
                    values.update(result.normalized_value)
                else:
                    values[field] = result.normalized_value
                results[field] = result
                source = self._source_for(field, eligible_decisions)
                issue = quality_issue(
                    source_file_id=source_file_id,
                    source_row_number=row.row_number,
                    source_column=source,
                    normalized_column=self._normalized_source_for(source, eligible_decisions),
                    target_field=field,
                    raw_value=row.raw_values.get(source),
                    result=result,
                )
                if issue:
                    row_issues.append(issue)

            for field in self.required_fields:
                if field not in results:
                    result = ValidationResult(
                        status=ValidationStatus.MISSING,
                        issue_code="MISSING_REQUIRED_FIELD",
                        message=f"Required field {field!r} was not supplied.",
                        severity=IssueSeverity.ERROR,
                    )
                    results[field] = result
                    source = self._source_for(field, eligible_decisions)
                    row_issues.append(
                        QualityIssue(
                            source_file_id=source_file_id,
                            source_row_number=row.row_number,
                            source_column=source,
                            normalized_column=self._normalized_source_for(
                                source, eligible_decisions
                            ),
                            target_field=field,
                            raw_value=row.raw_values.get(source),
                            normalized_value=None,
                            issue_code=result.issue_code,
                            severity=IssueSeverity.ERROR,
                            message=result.message or "Missing required field.",
                        )
                    )

            candidate = CanonicalRecord(
                source_row_number=row.row_number,
                **{
                    key: value
                    for key, value in values.items()
                    if key in _CANONICAL_FIELDS
                },
            )
            if candidate.cccd is not None:
                cross_field_issues = validate_cccd_cross_fields(
                    row_context, candidate, self._source_for("cccd", eligible_decisions)
                )
                identifier_validation_issues.extend(cross_field_issues)
                row_issues.extend(cross_field_issues)
            issues.extend(row_issues)
            rejecting_results = [
                results[field] for field in self.required_fields if field in results
            ]
            if "cccd" in results:
                rejecting_results.append(results["cccd"])
            if self.row_quality_policy.rejects(rejecting_results) or any(
                issue.severity is IssueSeverity.ERROR
                for issue in identifier_validation_issues
            ):
                rejected.append(row)
            else:
                accepted.append(candidate)
                source_columns_by_row[row.row_number] = {
                    field: self._source_for(field, eligible_decisions)
                    for field in ("cccd", "ma_bhyt")
                    if getattr(candidate, field) is not None
                }

        cross_issues = validate_cross_records(
            CrossRecordValidationContext(
                source_file_id=source_file_id,
                records=accepted,
                source_columns=source_columns_by_row,
                identity_key_fields=self.identity_key_fields,
            )
        )
        if cross_issues:
            issues.extend(cross_issues)
            rejected_numbers = {issue.source_row_number for issue in cross_issues}
            rejected.extend(
                row for row in dataset.rows if row.row_number in rejected_numbers
            )
            accepted = [
                row for row in accepted if row.source_row_number not in rejected_numbers
            ]

        return TransformResult(
            source_file_id=source_file_id,
            mapping_version=self.mapping_version,
            transform_version=self.transform_version,
            mapping_plan=plan,
            accepted_rows=accepted,
            rejected_rows=rejected,
            quality_issues=issues,
        )

    def _eligible_operations(
        self, operations: list[MappingOperation], source_file_id: UUID
    ) -> tuple[list[MappingOperation], Callable[[int, dict[str, Any]], Iterable[QualityIssue]]]:
        counts = Counter(
            target
            for operation in operations
            for target in operation.target_fields
            if target in _CANONICAL_FIELDS
        )

        ineligible = [
            operation
            for operation in operations
            if (
                operation.method is MappingMethod.UNKNOWN
                or operation.is_ambiguous
                or any(target not in _CANONICAL_FIELDS for target in operation.target_fields)
                or any(
                    counts.get(target, 0) > 1
                    and target not in {"cccd", "ma_bhyt"}
                    for target in operation.target_fields
                )
            )
        ]
        eligible = [operation for operation in operations if operation not in ineligible]

        def schema_issues(
            row_number: int, raw: dict[str, Any]
        ) -> Iterable[QualityIssue]:
            for operation in ineligible:
                source = operation.source_columns[0]
                normalized = normalize(source)
                if operation.method is MappingMethod.UNKNOWN:
                    code, severity, message = (
                        "UNKNOWN_SOURCE_COLUMN",
                        IssueSeverity.WARNING,
                        operation.reason or "Unknown source column.",
                    )
                else:
                    code, severity, message = (
                        "AMBIGUOUS_MAPPING",
                        IssueSeverity.WARNING,
                        operation.ambiguity_note or "Mapping requires an explicit override.",
                    )
                for target in operation.target_fields:
                    yield QualityIssue(
                        source_file_id=source_file_id,
                        source_row_number=row_number,
                        source_column=source,
                        normalized_column=normalized,
                        target_field=target,
                        raw_value=raw.get(source),
                        normalized_value=None,
                        issue_code=code,
                        severity=severity,
                        message=message,
                    )

        return eligible, schema_issues

    @staticmethod
    def _extract(operation: MappingOperation, raw: dict[str, Any]):
        source_values = {column: raw.get(column) for column in operation.source_columns}
        config = operation.transformation
        target = operation.target_fields[0]
        extractor_name = operation.extractor

        if extractor_name == "direct":
            return DirectExtractor(target).extract(
                raw.get(operation.source_columns[0]),
                source_column=operation.source_columns[0],
            )
        if extractor_name == "extract_gender":
            return GenderExtractor(target).extract(
                raw.get(operation.source_columns[0]),
                source_column=operation.source_columns[0],
            )
        if extractor_name == "extract_indicator_gender":
            return GenderExtractor(
                target,
                indicator_columns=config.get("indicator_columns") or {},
            ).extract(source_values=source_values)
        if extractor_name == "extract_blood_pressure":
            return BloodPressureExtractor(
                systolic_field=operation.target_fields[0],
                diastolic_field=operation.target_fields[1],
                separators=tuple(config.get("separators") or ("/",)),
            ).extract(source_values=source_values)
        if extractor_name == "extract_combined_icd":
            return ICDExtractor(
                target_fields=operation.target_fields,
                separators=tuple(config.get("separators") or ("/",)),
            ).extract(source_values=source_values)
        if extractor_name == "extract_split_name":
            return SplitNameExtractor(target).extract(source_values=source_values)
        if extractor_name == "extract_year_from_date":
            return DateExtractor(target).extract(
                raw.get(operation.source_columns[0]),
                source_column=operation.source_columns[0],
            )
        if extractor_name == "extract_date":
            return DateExtractor(
                target, slash_convention=config.get("slash_convention")
            ).extract(
                raw.get(operation.source_columns[0]),
                source_column=operation.source_columns[0],
            )
        raise ValueError(f"Unknown mapping extractor {extractor_name!r}")

    def _validate(
        self, field: str, value: Any, values: dict[str, Any]
    ) -> ValidationResult | None:
        if field in {"huyet_ap_tam_thu", "huyet_ap_tam_truong"}:
            return validate_blood_pressure(
                values.get("huyet_ap_tam_thu"), values.get("huyet_ap_tam_truong")
            )
        validator = _VALIDATORS.get(field)
        return validator(value) if validator else None

    @staticmethod
    def _source_for(field: str, decisions: list[Any]) -> str:
        for decision in decisions:
            if decision.target_field == field:
                return decision.source_columns[0]
        return "<unmapped>"

    @staticmethod
    def _normalized_source_for(source: str, decisions: list[Any]) -> str | None:
        for decision in decisions:
            for column, normalized in zip(
                decision.source_columns, decision.normalized_columns, strict=True
            ):
                if column == source:
                    return normalized
        return None


def process_file(**kwargs: Any) -> TransformResult:
    """Convenience API for callers that do not need pipeline customization."""
    return TransformationPipeline().process(**kwargs)
