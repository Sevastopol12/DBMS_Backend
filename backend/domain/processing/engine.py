from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from backend.database.canonical import (
    CANONICAL_FIELD_NAMES,
    CANONICAL_FIELD_SET,
    IDENTITY_FIELDS,
)
from backend.timezone import today_vietnam

from .mapping import MappingCatalog, MappingSource, match_headers
from .merge import FieldCandidate, RowCandidate, merge_candidates
from .models import (
    AcceptedRecord,
    ColumnMap,
    DuplicateRole,
    FieldPlan,
    FieldQuality,
    FileAcceptancePolicy,
    FileDecision,
    MappingOperation,
    MappingPlan,
    ProcessingStage,
    QualityReport,
    ReportRow,
    RowDecision,
    RowDisposition,
    SourceDataset,
    TransformResult,
    safe_issue_sample,
)
from .reader import read_source_dataset
from .reserved_columns import strip_reserved
from .transformation import crossfield
from .transformation.normalization import (
    normalize_date,
    normalize_datetime,
    normalize_header,
    normalize_identifier,
    normalize_measurement,
    normalize_text,
)
from .transformation.operations import execute_operation
from .transformation.validation import ValidationResult, ValidationState, validate_field


@dataclass
class _RowAccumulator:
    issue_codes: list[str] = field(default_factory=list)

    def add_issue(self, code: str | None) -> None:
        if (
            code
            and code != "MISSING"
            and not code.startswith("MISSING:")
            and code not in self.issue_codes
        ):
            self.issue_codes.append(code)

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
            reference_date or self.policy.validation.reference_date or today_vietnam()
        )

    async def transform(
        self, file_id: UUID, filename: str, file_content: bytes
    ) -> TransformResult:
        dataset = read_source_dataset(
            filename=filename, source_file_id=file_id, file_bytes=file_content
        )
        return self.transform_dataset(dataset)

    def transform_dataset(self, dataset: SourceDataset) -> TransformResult:
        headers, clean_rows = strip_reserved(dataset.headers, dataset.rows)
        plan = self.build_mapping_plan(headers, clean_rows)

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
            quality.accepted_rows = 0
            quality.rejected_rows = len(dataset.rows)
            quality.ignored_duplicate_row_count = 0
            self._add_issues(quality, mapping_reasons)
            quality.decision = FileDecision.REJECTED
            quality.processing_stage = ProcessingStage.POLICY
            if not quality.counts_balanced:
                raise RuntimeError("Quality counters are not balanced")
            return TransformResult(
                file_id=dataset.source_file_id,
                rejected_row_count=len(dataset.rows),
                quality_report=quality,
                source=dataset,
            )

        groups: dict[
            tuple[Any, ...],
            list[tuple[RowCandidate, dict[str, Any], dict[str, ValidationResult]]],
        ] = {}
        for index, source_row in enumerate(clean_rows, start=2):
            values, results = self._validate_fields(index, source_row, plan, quality)
            candidate = RowCandidate(
                index,
                {
                    name: FieldCandidate(
                        values.get(name), result.state, result.issue_code
                    )
                    for name, result in results.items()
                },
            )
            valid_identity = all(
                results[name].state is ValidationState.VALID for name in IDENTITY_FIELDS
            )
            key = (
                tuple(values[name] for name in IDENTITY_FIELDS)
                if valid_identity
                else ("unkeyed", index)
            )
            groups.setdefault(key, []).append((candidate, values, results))

        accepted_records: list[AcceptedRecord] = []
        decisions: list[RowDecision] = []
        for members in groups.values():
            candidates = [member[0] for member in members]
            row_numbers = [candidate.row_number for candidate in candidates]
            merged = merge_candidates(candidates)
            values = dict(merged.values)
            required_issues = [
                f"REQUIRED_FIELD_{'MISSING' if merged.states.get(name) is ValidationState.MISSING else 'INVALID'}:{name}"
                for name in self.policy.required_fields
                if merged.states.get(name) is not ValidationState.VALID
            ]
            own_issues = {}
            for candidate, _, results in members:
                own_issues[candidate.row_number] = [
                    f"{result.issue_code}:{name}"
                    for name, result in results.items()
                    if result.state is ValidationState.INVALID and result.issue_code
                ]
            cross_issues = self._apply_crossfield(
                values, quality, row_numbers[0], _RowAccumulator()
            )
            group_issues = list(dict.fromkeys([*required_issues, *cross_issues]))
            if not group_issues:
                for name in CANONICAL_FIELD_NAMES:
                    if merged.states.get(name) is not ValidationState.VALID:
                        values[name] = None
                try:
                    row = ReportRow(**values)
                    accepted_records.append(
                        AcceptedRecord(
                            row=row,
                            primary_row_number=row_numbers[0],
                            contributing_row_numbers=row_numbers,
                        )
                    )
                    quality.accepted_rows += 1
                    quality.ignored_duplicate_row_count += len(row_numbers) - 1
                    for row_number in row_numbers[1:]:
                        decisions.append(
                            RowDecision(
                                source_row_number=row_number,
                                disposition=RowDisposition.ACCEPTED,
                                duplicate_role=DuplicateRole.MERGED,
                                merged_into_row=row_numbers[0],
                                group_row_numbers=row_numbers,
                            )
                        )
                except ValueError:
                    group_issues = ["ROW_VALIDATION_FAILED"]
            if group_issues:
                for position, row_number in enumerate(row_numbers):
                    codes = list(
                        dict.fromkeys([*group_issues, *own_issues[row_number]])
                    )
                    decisions.append(
                        RowDecision(
                            source_row_number=row_number,
                            disposition=RowDisposition.REJECTED,
                            duplicate_role=DuplicateRole.PRIMARY
                            if position == 0
                            else DuplicateRole.MERGED,
                            merged_into_row=None if position == 0 else row_numbers[0],
                            group_row_numbers=row_numbers,
                            issue_codes=codes,
                        )
                    )
                    quality.rejected_rows += 1
                    self._add_issues(quality, codes, row_number)

        quality.processing_stage = ProcessingStage.COMPLETED
        quality.decision = FileDecision.ACCEPTED

        if not quality.counts_balanced:
            raise RuntimeError("Quality counters are not balanced")

        return TransformResult(
            file_id=dataset.source_file_id,
            accepted_records=accepted_records,
            decisions=decisions,
            accepted_row_count=len(accepted_records),
            rejected_row_count=quality.rejected_rows,
            ignored_duplicate_row_count=quality.ignored_duplicate_row_count,
            quality_report=quality,
            source=dataset,
        )

    def _validate_fields(
        self,
        index: int,
        source_row: dict[str, Any],
        plan: MappingPlan,
        quality: QualityReport,
    ) -> tuple[dict[str, Any], dict[str, ValidationResult]]:
        values: dict[str, Any] = {}
        validation_results: dict[str, ValidationResult] = {}

        for can_field in CANONICAL_FIELD_NAMES:
            plan_for_field = plan.field_plans.get(can_field)
            if plan_for_field is None:
                result = validate_field(
                    can_field,
                    None,
                    policy=self.policy.validation,
                    reference_date=self.reference_date,
                )
                validation_results[can_field] = result
                quality.field_quality[can_field].missing += 1
                values[can_field] = None
                continue
            try:
                raw_value = self._execute_field_plan(plan_for_field, source_row)
                value = self._normalize_value(can_field, raw_value)
                result = validate_field(
                    can_field,
                    value,
                    policy=self.policy.validation,
                    reference_date=self.reference_date,
                )
                validation_results[can_field] = result
                if result.normalized_value is not None:
                    value = result.normalized_value
                values[can_field] = value
                stats = quality.field_quality[can_field]
                if result.state is ValidationState.VALID:
                    stats.valid += 1
                elif result.state is ValidationState.MISSING:
                    stats.missing += 1
                else:
                    stats.invalid += 1
                    self._add_issues(
                        quality,
                        [f"{result.issue_code or 'INVALID_VALUE'}:{can_field}"],
                        index,
                    )
            except (TypeError, ValueError, KeyError):
                quality.field_quality[can_field].invalid += 1
                values[can_field] = None
                validation_results[can_field] = ValidationResult(
                    state=ValidationState.INVALID, issue_code="INVALID_VALUE"
                )
                self._add_issues(quality, [f"INVALID_VALUE:{can_field}"], index)

        return values, validation_results

    def _apply_crossfield(
        self,
        values: dict[str, Any],
        quality: QualityReport,
        index: int,
        acc: _RowAccumulator,
    ) -> list[str]:
        crossfield_rejection_issues: list[str] = []
        for issue in crossfield.check_row(values, reference_date=self.reference_date):
            if issue.code == "VISIT_BEFORE_BIRTH" and issue.severity == "INVALID":
                issue_code = f"XFIELD:{issue.code}"
                acc.add_issue(issue_code)
                crossfield_rejection_issues.append(issue_code)
            else:
                # Informational findings never reject and never appear in
                # row decisions; they are only counted in the quality report.
                self._add_issues(quality, [f"INFO:{issue.code}"], index)
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
            # detailed INVALID_VISIT_DATE issue code is preserved. Truncate
            # to whole seconds per D-01; naive input is Vietnam local time.
            if normalized is None:
                return value
            return normalized.replace(microsecond=0)
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
