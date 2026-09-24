from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from backend.domain.models import (
    FieldPlan,
    FieldQuality,
    FileAcceptancePolicy,
    FileDecision,
    MappingOperation,
    MappingPlan,
    ProcessingStage,
    QualityReport,
    RowDisposition,
    RowIssueRecord,
    RuleMode,
    TransformResult,
    safe_issue_sample,
)

from .canonical import ACCEPTANCE_FIELDS, CANONICAL_FIELD_NAMES, CANONICAL_FIELD_SET
from .mapping import MappingCatalog, MappingSource, match_headers
from . import crossfield
from .normalization import (
    normalize_date,
    normalize_header,
    normalize_identifier,
    normalize_measurement,
    normalize_datetime,
    normalize_text,
)
from .operations import execute_operation
from .reader import read_source_dataset
from .validation import ValidationResult, ValidationState, validate_field
from backend.domain.models import ColumnMap, ReportRow, SourceDataset


@dataclass(frozen=True)
class _RowTransformResult:
    accepted_row: ReportRow | None = None
    review_record: RowIssueRecord | None = None


@dataclass
class _RowAccumulator:
    issue_codes: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def add_issue(self, code: str | None) -> None:
        if (
            code
            and code != "MISSING"
            and not code.startswith("MISSING:")
            and code not in self.issue_codes
        ):
            self.issue_codes.append(code)

    def add_flag(self, code: str) -> None:
        if code == "MISSING" or code.startswith("MISSING:"):
            return
        if code not in self.flags:
            self.flags.append(code)
        self.add_issue(code)

    def add_field_issue(self, code: str | None, field_name: str) -> None:
        if code and code != "MISSING" and not code.startswith("MISSING:"):
            self.add_issue(f"{code}:{field_name}")


class TransformPipeline:
    """Coordinate transformation stages and aggregate safe row-quality data."""

    def __init__(
        self,
        mapping_cache: MappingSource | None = None,
        explicit_mapping: dict[str, Any] | None = None,
        policy: FileAcceptancePolicy | None = None,
        operation_handlers: dict[MappingOperation, Any] | None = None,
        reference_date: date | None = None,
    ) -> None:
        self.mapping_cache = mapping_cache
        self.explicit_mapping = explicit_mapping or {}
        self.policy = policy or FileAcceptancePolicy()
        self.operation_handlers = operation_handlers or {}
        self.reference_date = (
            reference_date or self.policy.validation.reference_date or date.today()
        )

    async def transform(
        self, file_id: UUID, filename: str, file_content: bytes
    ) -> TransformResult:
        dataset = read_source_dataset(
            filename=filename, source_file_id=file_id, file_bytes=file_content
        )
        return self.transform_dataset(dataset)

    def transform_dataset(self, dataset: SourceDataset) -> TransformResult:
        plan = self.build_mapping_plan(dataset.headers, dataset.rows)

        quality = QualityReport(
            file_id=dataset.source_file_id,
            processing_stage=ProcessingStage.MAPPING,
            total_target_fields=plan.total_target_fields,
            mapped_target_fields=plan.mapped_target_fields,
            coverage_ratio=plan.coverage_ratio,
            unmapped_headers=plan.unmapped_headers,
            ambiguous_headers=plan.ambiguous_headers,
            total_rows=len(dataset.rows),
            field_quality={field: FieldQuality() for field in CANONICAL_FIELD_NAMES},
        )

        mapping_reasons = self.policy.mapping_rejection_reasons(plan)
        if mapping_reasons:
            quality.rejected_rows = len(dataset.rows)
            self._add_issues(quality, mapping_reasons)
            quality.decision = FileDecision.REJECTED
            quality.processing_stage = ProcessingStage.POLICY
            return TransformResult(
                file_id=dataset.source_file_id,
                rejected_row_count=len(dataset.rows),
                quality_report=quality,
            )

        accepted_rows: list[ReportRow] = []
        accepted_numbers: list[int] = []
        review_records = []
        for index, source_row in enumerate(dataset.rows, start=2):
            row_result = self._transform_row(index, source_row, plan, quality)
            if row_result.accepted_row is not None:
                accepted_rows.append(row_result.accepted_row)
                accepted_numbers.append(index)
            if row_result.review_record is not None:
                review_records.append(row_result.review_record)

        quality.processing_stage = ProcessingStage.VALIDATION
        policy_reasons = self.policy.row_rejection_reasons(
            quality,
            accepted_rows=quality.accepted_rows,
            total_rows=quality.total_rows,
        )
        if policy_reasons:
            self._add_issues(quality, policy_reasons)
            quality.decision = FileDecision.REJECTED
            quality.processing_stage = ProcessingStage.POLICY
            accepted_rows = []
            accepted_numbers = []
        else:
            quality.decision = FileDecision.ACCEPTED
            quality.processing_stage = ProcessingStage.COMPLETED

        return TransformResult(
            file_id=dataset.source_file_id,
            accepted_rows=accepted_rows,
            accepted_row_numbers=accepted_numbers,
            accepted_row_count=len(accepted_rows),
            rejected_row_count=quality.rejected_rows,
            quality_report=quality,
            review_records=review_records,
        )

    def _transform_row(
        self,
        index: int,
        source_row: dict[str, Any],
        plan: MappingPlan,
        quality: QualityReport,
    ) -> _RowTransformResult:
        acc = _RowAccumulator()
        values, validation_results = self._validate_fields(
            index,
            source_row,
            plan,
            quality,
            acc,
        )

        crossfield_rejection_issues = self._apply_crossfield(
            values,
            quality,
            index,
            acc,
        )

        acceptance_issues = self._acceptance_issues(values, validation_results)
        for issue in acceptance_issues:
            acc.add_issue(issue)

        row_rejection_issues = [*acceptance_issues, *crossfield_rejection_issues]
        if row_rejection_issues:
            quality.rejected_rows += 1
            self._add_issues(quality, row_rejection_issues, index)
            if acc.flags:
                quality.flagged_rows += 1
            return _RowTransformResult(
                review_record=RowIssueRecord(
                    source_row_number=index,
                    disposition=RowDisposition.REJECTED,
                    issue_codes=acc.issue_codes,
                )
            )

        try:
            # ReportRow keeps its canonical typed schema.  A malformed
            # visit date remains a validation diagnostic, but is not a
            # production acceptance criterion and cannot make the row
            # fail model construction.
            report_values = dict(values)
            if validation_results.get("ngay_kham") and (
                validation_results["ngay_kham"].state is ValidationState.INVALID
            ):
                report_values["ngay_kham"] = None
            accepted_row = ReportRow(**report_values)
            quality.accepted_rows += 1
            if acc.flags:
                quality.flagged_rows += 1
                review_record = RowIssueRecord(
                    source_row_number=index,
                    disposition=RowDisposition.ACCEPTED_WITH_FLAGS,
                    issue_codes=acc.flags,
                )
            else:
                review_record = None
            return _RowTransformResult(
                accepted_row=accepted_row,
                review_record=review_record,
            )
        except ValueError:
            quality.rejected_rows += 1
            acc.add_issue("ROW_VALIDATION_FAILED")
            self._add_issues(quality, ["ROW_VALIDATION_FAILED"], index)
            if acc.flags:
                quality.flagged_rows += 1
            return _RowTransformResult(
                review_record=RowIssueRecord(
                    source_row_number=index,
                    disposition=RowDisposition.REJECTED,
                    issue_codes=acc.issue_codes,
                )
            )

    def _validate_fields(
        self,
        index: int,
        source_row: dict[str, Any],
        plan: MappingPlan,
        quality: QualityReport,
        acc: _RowAccumulator,
    ) -> tuple[dict[str, Any], dict[str, ValidationResult]]:
        values: dict[str, Any] = {}
        validation_results: dict[str, ValidationResult] = {}

        for field in CANONICAL_FIELD_NAMES:
            plan_for_field = plan.field_plans.get(field)
            if plan_for_field is None:
                result = validate_field(
                    field,
                    None,
                    policy=self.policy.validation,
                    reference_date=self.reference_date,
                )
                validation_results[field] = result
                quality.field_quality[field].missing += 1
                values[field] = None
                acc.add_field_issue(result.issue_code, field)
                for flag in result.flags:
                    acc.add_flag(flag)
                continue
            try:
                raw_value = self._execute_field_plan(plan_for_field, source_row)
                value = self._normalize_value(field, raw_value)
                result = validate_field(
                    field,
                    value,
                    policy=self.policy.validation,
                    reference_date=self.reference_date,
                )
                validation_results[field] = result
                if result.normalized_value is not None:
                    value = result.normalized_value
                values[field] = value
                acc.add_field_issue(result.issue_code, field)
                for flag in result.flags:
                    acc.add_flag(flag)
                    self._add_issues(quality, [f"FLAG:{flag}"], index)
                stats = quality.field_quality[field]
                if result.state is ValidationState.VALID:
                    stats.valid += 1
                elif result.state is ValidationState.MISSING:
                    stats.missing += 1
                elif result.state is ValidationState.SUSPICIOUS:
                    stats.suspicious += 1
                    if result.issue_code:
                        self._add_issues(
                            quality, [f"{result.issue_code}:{field}"], index
                        )
                else:
                    stats.invalid += 1
                    self._add_issues(
                        quality,
                        [f"{result.issue_code or 'INVALID_VALUE'}:{field}"],
                        index,
                    )
            except (TypeError, ValueError, KeyError):
                quality.field_quality[field].invalid += 1
                values[field] = None
                acc.add_issue(f"INVALID_VALUE:{field}")
                self._add_issues(quality, [f"INVALID_VALUE:{field}"], index)

        return values, validation_results

    @staticmethod
    def _is_populated(value: Any) -> bool:
        return value is not None and not (isinstance(value, str) and not value.strip())

    def _acceptance_issues(
        self,
        values: dict[str, Any],
        validation_results: dict[str, ValidationResult],
    ) -> list[str]:
        missing_acceptance = [
            field
            for field in ACCEPTANCE_FIELDS
            if not self._is_populated(values.get(field))
        ]
        acceptance_issues = [
            f"REQUIRED_FIELD_MISSING:{field}" for field in missing_acceptance
        ]
        invalid_acceptance = [
            field
            for field in ACCEPTANCE_FIELDS
            if field not in missing_acceptance
            and field in validation_results
            and validation_results[field].state is not ValidationState.VALID
        ]
        acceptance_issues.extend(
            f"REQUIRED_FIELD_{validation_results[field].state.value}:{field}"
            for field in invalid_acceptance
        )
        return acceptance_issues

    def _apply_crossfield(
        self,
        values: dict[str, Any],
        quality: QualityReport,
        index: int,
        acc: _RowAccumulator,
    ) -> list[str]:
        crossfield_rejection_issues: list[str] = []
        for issue in crossfield.check_row(values, reference_date=self.reference_date):
            mode = (
                self.policy.validation.cccd_structure
                if issue.code.startswith("CCCD_")
                else self.policy.validation.cross_field
            )
            if mode is RuleMode.OFF:
                continue
            if mode is RuleMode.FLAG or issue.severity != "INVALID":
                acc.add_flag(issue.code)
                self._add_issues(quality, [f"FLAG:{issue.code}"], index)
            else:
                issue_code = f"XFIELD:{issue.code}"
                acc.add_issue(issue_code)
                crossfield_rejection_issues.append(issue_code)
        return crossfield_rejection_issues

    def build_mapping_plan(
        self, headers: list[str], rows: list[dict[str, Any]] | None = None
    ) -> MappingPlan:
        explicit = dict(self.explicit_mapping)
        column_maps = self.get_explicit_column_maps(headers)
        catalog = MappingCatalog.for_task(self.mapping_cache)
        resolved, ambiguous, unmapped_headers = match_headers(
            self.mapping_cache,
            column_maps,
            rows=rows,
            explicit_map=explicit,
            catalog=catalog,
        )
        by_target: dict[str, list[Any]] = defaultdict(list)
        unmapped: list[str] = []
        for result in resolved:
            for target in result.entry.output_targets:
                if target not in CANONICAL_FIELD_SET:
                    unmapped.append(result.source.original_name)
                    continue
                by_target[target].append(result)

        field_plans: list[FieldPlan] = []
        for target, columns in by_target.items():
            entries = [column.entry for column in columns]
            operation = (
                entries[0].operation if len(entries) == 1 else MappingOperation.COALESCE
            )
            if any(entry.operation is MappingOperation.CONCAT for entry in entries):
                operation = MappingOperation.CONCAT
            if any(
                entry.operation is MappingOperation.SPLIT_BLOOD_PRESSURE
                for entry in entries
            ):
                operation = MappingOperation.SPLIT_BLOOD_PRESSURE
            if any(entry.operation is MappingOperation.SPLIT_ICD for entry in entries):
                operation = MappingOperation.SPLIT_ICD
            if target == "gioi_tinh" and len(entries) > 1:
                operation = MappingOperation.DERIVE_GENDER_FROM_FLAGS
            metadata: dict[str, Any] = {}
            for entry in entries:
                metadata.update(entry.metadata)
            if operation is MappingOperation.SPLIT_BLOOD_PRESSURE:
                metadata["component"] = (
                    "systolic" if target == "huyet_ap_tam_thu" else "diastolic"
                )
            field_plans.append(
                FieldPlan(
                    target_field=target,
                    source_columns=[column.source.original_name for column in columns],
                    operation=operation,
                    confidence=max(column.score for column in columns),
                    metadata=metadata,
                )
            )

        return MappingPlan.from_field_plans(
            field_plans,
            unmapped_headers=[
                *unmapped,
                *(column.original_name for column in unmapped_headers),
                *(column.original_name for column in ambiguous),
            ],
            ambiguous_headers=[column.original_name for column in ambiguous],
        )

    def get_explicit_column_maps(self, headers: list[str]) -> list[ColumnMap]:
        result: list[ColumnMap] = []
        for header in headers:
            configured = self._explicit_value_for_target(header)
            result.append(
                ColumnMap(
                    original_name=header,
                    normalized_name=normalize_header(header),
                    mapping_target=self._mapping_target(configured),
                )
            )
        return result

    def _execute_field_plan(self, plan: FieldPlan, row: dict[str, Any]) -> Any:
        handler = self.operation_handlers.get(plan.operation)
        if handler is not None:
            return handler(plan, row)
        return execute_operation(plan, row)

    @staticmethod
    def _normalize_value(field: str, value: Any) -> Any:
        if field == "ngay_kham":
            if normalize_text(value) is None:
                return None
            normalized = normalize_datetime(value)
            # Keep an unparseable value for semantic validation so the
            # detailed INVALID_VISIT_DATE issue code is preserved.
            return normalized if normalized is not None else value
        if field == "nam_sinh":
            text = normalize_text(value)
            if text is None or text.isdigit() and len(text) == 4:
                return text
            return normalize_date(value) or text
        if field in {"cccd", "ma_bhyt", "sdt"}:
            return normalize_identifier(value)
        if field in {
            "huyet_ap_tam_thu",
            "huyet_ap_tam_truong",
            "chi_so_duong_huyet",
            "chi_so_hba1c",
        }:
            normalized = normalize_measurement(value)
            return normalized if normalized is not None else normalize_text(value)
        return normalize_text(value)

    def _explicit_value_for_target(self, header: str) -> Any:
        return self.explicit_mapping.get(header) or self.explicit_mapping.get(
            normalize_header(header)
        )

    @staticmethod
    def _mapping_target(value: Any) -> str | None:
        if isinstance(value, dict):
            value = value.get(
                "target_field", value.get("mapping_target", value.get("target"))
            )
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _add_issues(
        quality: QualityReport, issues: list[str], row_number: int | None = None
    ) -> None:
        for issue in issues:
            quality.issue_code_counts[issue] = (
                quality.issue_code_counts.get(issue, 0) + 1
            )
            if row_number is not None and len(quality.safe_error_samples) < 20:
                quality.safe_error_samples.append(safe_issue_sample(row_number, issue))


__all__ = ["TransformPipeline"]
