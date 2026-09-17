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
)
from backend.domain.ingestion.mapping import resolve_headers
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
            decisions=[item.decision for item in report.decisions],
        )

        eligible, schema_issues = self._eligible_decisions(
            report.decisions, source_file_id
        )

        accepted: list[CanonicalRecord] = []
        rejected = []
        issues: list[QualityIssue] = []
        source_columns_by_row: dict[int, dict[str, str]] = {}

        for row in dataset.rows:
            row_issues = list(schema_issues(row.row_number, row.raw_values))

            # Validate ID
            identifier_validation_issues: list[QualityIssue] = []
            identifier_sources = {
                field: [d.original_header for d in eligible if d.target_field == field]
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

            processed_fanout_sources: set[str] = set()

            for decision in eligible:
                targets_for_source = [
                    d.target_field
                    for d in eligible
                    if d.original_header == decision.original_header
                ]

                if (
                    len(targets_for_source) > 1
                    and decision.original_header in processed_fanout_sources
                ):
                    continue

                extraction = self._extract(decision, eligible, row.raw_values)

                if len(targets_for_source) > 1:
                    processed_fanout_sources.add(decision.original_header)

                for field, extracted_value in extraction.values.items():
                    # Multiple mapped identifier columns are retained for row-level
                    # comparison.  The first header-order value is deterministic;
                    # conflicts are reported below and never silently accepted.
                    if field not in values or field not in {"cccd", "ma_bhyt"}:
                        values[field] = extracted_value

                for extraction_issue in extraction.issues:
                    for target in extraction_issue.target_fields:
                        source = (
                            extraction_issue.source_columns[0]
                            if extraction_issue.source_columns
                            else "<row>"
                        )
                        raw = extraction_issue.raw_values.get(source)
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
                                source, eligible
                            ),
                            target_field=target,
                            raw_value=raw,
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
                source = self._source_for(field, eligible)
                issue = quality_issue(
                    source_file_id=source_file_id,
                    source_row_number=row.row_number,
                    source_column=source,
                    normalized_column=self._normalized_source_for(source, eligible),
                    target_field=field,
                    raw_value=row.raw_values.get(source),
                    result=result,
                )
                if issue:
                    row_issues.append(issue)

            # Required fields are checked even if unmapped or absent.
            for field in self.required_fields:
                if field not in results:
                    result = ValidationResult(
                        status=ValidationStatus.MISSING,
                        issue_code="MISSING_REQUIRED_FIELD",
                        message=f"Required field {field!r} was not supplied.",
                        severity=IssueSeverity.ERROR,
                    )
                    results[field] = result
                    source = self._source_for(field, eligible)
                    row_issues.append(
                        QualityIssue(
                            source_file_id=source_file_id,
                            source_row_number=row.row_number,
                            source_column=source,
                            normalized_column=self._normalized_source_for(
                                source, eligible
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
                    row_context, candidate, self._source_for("cccd", eligible)
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
                    field: self._source_for(field, eligible)
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

    def _eligible_decisions(
        self, decisions: list[Any], source_file_id: UUID
    ) -> tuple[list[Any], Callable[[int, dict[str, Any]], Iterable[QualityIssue]]]:
        counts = Counter(
            d.target_field for d in decisions if d.target_field in _CANONICAL_FIELDS
        )

        ineligible = [
            d
            for d in decisions
            if (
                d.method is MappingMethod.UNKNOWN
                or d.is_ambiguous
                or d.target_field not in _CANONICAL_FIELDS
                or (counts.get(d.target_field, 0) > 1 and d.target_field not in {"cccd", "ma_bhyt"})
            )
        ]
        eligible = [d for d in decisions if d not in ineligible]

        def schema_issues(
            row_number: int, raw: dict[str, Any]
        ) -> Iterable[QualityIssue]:
            for d in ineligible:
                if d.method is MappingMethod.UNKNOWN:
                    code, severity, message = (
                        "UNKNOWN_SOURCE_COLUMN",
                        IssueSeverity.WARNING,
                        d.reason or "Unknown source column.",
                    )
                else:
                    code, severity, message = (
                        "AMBIGUOUS_MAPPING",
                        IssueSeverity.WARNING,
                        d.ambiguity_note or "Mapping requires an explicit override.",
                    )
                yield QualityIssue(
                    source_file_id=source_file_id,
                    source_row_number=row_number,
                    source_column=d.original_header,
                    normalized_column=d.normalized_header,
                    target_field=d.target_field,
                    raw_value=raw.get(d.original_header),
                    normalized_value=None,
                    issue_code=code,
                    severity=severity,
                    message=message,
                )

        return eligible, schema_issues

    def _extract(self, decision: Any, decisions: list[Any], raw: dict[str, Any]):
        source_values = {
            column: raw.get(column) for column in decision.decision.source_columns
        }
        # Structural fan-out decisions need one extraction per source column.
        same_source_targets = [
            d.target_field
            for d in decisions
            if d.original_header == decision.original_header
        ]

        if (
            decision.target_field in {"huyet_ap_tam_thu", "huyet_ap_tam_truong"}
            and len(same_source_targets) == 2
        ):
            return BloodPressureExtractor().extract(source_values=source_values)

        if decision.target_field == "gioi_tinh":
            return GenderExtractor().extract(
                raw.get(decision.original_header),
                source_column=decision.original_header,
            )

        if decision.target_field == "nam_sinh":
            return DateExtractor("nam_sinh").extract(
                raw.get(decision.original_header),
                source_column=decision.original_header,
            )

        if decision.target_field == "ngay_kham":
            return DateExtractor("ngay_kham").extract(
                raw.get(decision.original_header),
                source_column=decision.original_header,
            )

        if (
            decision.target_field in {"icd_tha", "icd_dtd"}
            and len(same_source_targets) == 2
        ):
            return ICDExtractor(target_fields=("icd_tha", "icd_dtd")).extract(
                source_values=source_values
            )

        return DirectExtractor(decision.target_field).extract(
            raw.get(decision.original_header), source_column=decision.original_header
        )

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
                return decision.original_header
        return "<unmapped>"

    @staticmethod
    def _normalized_source_for(source: str, decisions: list[Any]) -> str | None:
        for decision in decisions:
            if decision.original_header == source:
                return decision.normalized_header
        return None


def process_file(**kwargs: Any) -> TransformResult:
    """Convenience API for callers that do not need pipeline customization."""
    return TransformationPipeline().process(**kwargs)
