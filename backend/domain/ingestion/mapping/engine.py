"""Deterministic schema-mapping engine.

The mapping layer resolves source columns into explicit mapping operations.
An operation can consume multiple source columns and can fan out to multiple
canonical targets.  Extractor selection is carried by the operation metadata;
consumers must never infer extractor behavior from target-field names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.domain.ingestion.contracts import (
    MappingDecision,
    MappingMethod,
    MappingOperation,
)
from backend.domain.ingestion.header import HeaderInfo, build_header_index

from .aliases import (
    CANONICAL_FIELDS,
    DIRECT_ALIASES,
    EXTRACTOR_RULES,
    STRUCTURAL_RULES,
)

_CONFIDENCE_EXACT = 1.00
_CONFIDENCE_MANUAL = 1.00
_CONFIDENCE_STRUCTURAL_UNAMBIGUOUS = 0.95
_CONFIDENCE_STRUCTURAL_AMBIGUOUS = 0.70
_CONFIDENCE_UNKNOWN = 0.00
_ALIAS_AMBIGUITY_THRESHOLD = 0.60


@dataclass(frozen=True, slots=True)
class ExtendedMappingDecision:
    """Per-target projection of a mapping operation.

    ``source_columns`` is the complete source group.  Fan-out targets share the
    same ``operation_id`` so downstream extraction happens once per operation.
    """

    operation_id: str
    source_columns: tuple[str, ...]
    normalized_columns: tuple[str, ...]
    target_field: str
    method: MappingMethod
    confidence: float
    reason: str | None = None
    is_ambiguous: bool = False
    ambiguity_note: str | None = None
    extractor: str = "direct"
    transformation: dict[str, object] = field(default_factory=dict)

    @property
    def original_header(self) -> str:
        """Backward-compatible name for the first source column."""
        return self.source_columns[0]

    @property
    def normalized_header(self) -> str:
        """Backward-compatible name for the first normalized source column."""
        return self.normalized_columns[0]

    @property
    def decision(self) -> MappingDecision:
        """Return the stable contracts-layer flattened representation."""
        return MappingDecision(
            operation_id=self.operation_id,
            source_columns=list(self.source_columns),
            target_field=self.target_field,
            method=self.method,
            confidence=self.confidence,
            reason=self.reason,
            extractor=self.extractor,
            transformation=dict(self.transformation),
            is_ambiguous=self.is_ambiguous,
            ambiguity_note=self.ambiguity_note,
        )


def _structural_rules_for(normalized: str) -> list[dict[str, Any]]:
    """Return structural rules whose patterns contain *normalized*."""
    return [rule for rule in STRUCTURAL_RULES if normalized in rule["patterns"]]


def _extractor_metadata(header: str) -> tuple[str, dict[str, object]]:
    """Resolve extractor intent from the explicit source-header rule catalog."""
    rule = EXTRACTOR_RULES.get(header)
    if rule is None:
        return "direct", {}
    return str(rule["extractor"]), dict(rule.get("transformation") or {})


def _structural_metadata(rule: dict[str, Any]) -> tuple[str, dict[str, object]]:
    transformation = dict(rule.get("transformation") or {})
    transformation.setdefault("rule_type", rule.get("rule_type"))
    transformation.setdefault("description", rule.get("description", ""))
    return str(rule.get("extractor", "direct")), transformation


def _build_operation(
    *,
    operation_id: str,
    source_infos: list[HeaderInfo],
    target_fields: list[str],
    method: MappingMethod,
    confidence: float,
    reason: str | None,
    extractor: str,
    transformation: dict[str, object],
    is_ambiguous: bool = False,
    ambiguity_note: str | None = None,
) -> tuple[MappingOperation, list[ExtendedMappingDecision]]:
    source_columns = tuple(info.original_name for info in source_infos)
    normalized_columns = tuple(info.normalized_name for info in source_infos)
    operation = MappingOperation(
        operation_id=operation_id,
        source_columns=list(source_columns),
        target_fields=list(target_fields),
        method=method,
        confidence=confidence,
        reason=reason,
        extractor=extractor,
        transformation=dict(transformation),
        is_ambiguous=is_ambiguous,
        ambiguity_note=ambiguity_note,
    )
    decisions = [
        ExtendedMappingDecision(
            operation_id=operation_id,
            source_columns=source_columns,
            normalized_columns=normalized_columns,
            target_field=target,
            method=method,
            confidence=confidence,
            reason=reason,
            extractor=extractor,
            transformation=dict(transformation),
            is_ambiguous=is_ambiguous,
            ambiguity_note=ambiguity_note,
        )
        for target in target_fields
    ]
    return operation, decisions


def _resolve_manual(
    header_info: HeaderInfo,
    target: str,
    operation_id: str,
) -> tuple[MappingOperation, list[ExtendedMappingDecision]]:
    unknown_target = target not in CANONICAL_FIELDS
    note = (
        f"Manual override target {target!r} is not a known canonical field."
        if unknown_target
        else None
    )
    return _build_operation(
        operation_id=operation_id,
        source_infos=[header_info],
        target_fields=[target],
        method=MappingMethod.MANUAL,
        confidence=_CONFIDENCE_MANUAL,
        reason="Operator-supplied manual override.",
        extractor="direct",
        transformation={},
        is_ambiguous=unknown_target,
        ambiguity_note=note,
    )


def _resolve_structural_single(
    header_info: HeaderInfo,
    operation_id: str,
) -> list[tuple[MappingOperation, list[ExtendedMappingDecision]]]:
    matching_rules = [
        rule
        for rule in _structural_rules_for(header_info.normalized_name)
        if rule.get("mapping_mode") != "multi_source"
    ]
    if not matching_rules:
        return []

    ambiguous = len(matching_rules) > 1
    confidence = (
        _CONFIDENCE_STRUCTURAL_AMBIGUOUS
        if ambiguous
        else _CONFIDENCE_STRUCTURAL_UNAMBIGUOUS
    )
    note = (
        f"Normalized header {header_info.normalized_name!r} matches "
        f"{len(matching_rules)} structural rules; target is uncertain."
        if ambiguous
        else None
    )

    operations: list[tuple[MappingOperation, list[ExtendedMappingDecision]]] = []
    for index, rule in enumerate(matching_rules, start=1):
        targets = list(rule.get("targets") or [rule["target"]])
        extractor, transformation = _structural_metadata(rule)
        reason = (
            f"Structural rule '{rule['rule_type']}': "
            f"{rule.get('description', '')}"
        )
        op_id = operation_id if len(matching_rules) == 1 else f"{operation_id}.{index}"
        operations.append(
            _build_operation(
                operation_id=op_id,
                source_infos=[header_info],
                target_fields=targets,
                method=MappingMethod.STRUCTURAL,
                confidence=confidence,
                reason=reason,
                extractor=extractor,
                transformation=transformation,
                is_ambiguous=ambiguous,
                ambiguity_note=note,
            )
        )
    return operations


def _resolve_automatic(
    header_info: HeaderInfo,
    operation_id: str,
) -> tuple[list[tuple[MappingOperation, list[ExtendedMappingDecision]]], str]:
    """Resolve one remaining header using structural, exact, alias, unknown rules."""
    structural = _resolve_structural_single(header_info, operation_id)
    if structural:
        return structural, "structural"

    normalized = header_info.normalized_name
    entry = DIRECT_ALIASES.get(normalized)
    if entry is not None:
        method = MappingMethod.EXACT if normalized == entry.target else MappingMethod.ALIAS
        is_ambiguous = entry.confidence <= _ALIAS_AMBIGUITY_THRESHOLD
        note = (
            f"Alias confidence {entry.confidence:.2f} is at or below the ambiguity "
            f"threshold {_ALIAS_AMBIGUITY_THRESHOLD:.2f}; semantic meaning may differ."
            if is_ambiguous
            else None
        )
        extractor, transformation = _extractor_metadata(normalized)
        reason = (
            "Normalized header is itself a canonical field name."
            if method is MappingMethod.EXACT
            else f"Normalized alias {normalized!r} maps to {entry.target!r}."
        )
        operation = _build_operation(
            operation_id=operation_id,
            source_infos=[header_info],
            target_fields=[entry.target],
            method=method,
            confidence=_CONFIDENCE_EXACT if method is MappingMethod.EXACT else entry.confidence,
            reason=reason,
            extractor=extractor,
            transformation=transformation,
            is_ambiguous=is_ambiguous,
            ambiguity_note=note,
        )
        return [operation], "mapped"

    operation = _build_operation(
        operation_id=operation_id,
        source_infos=[header_info],
        target_fields=["UNKNOWN"],
        method=MappingMethod.UNKNOWN,
        confidence=_CONFIDENCE_UNKNOWN,
        reason=f"No alias, canonical field, or structural rule matched {normalized!r}.",
        extractor="direct",
        transformation={},
    )
    return [operation], "unknown"


@dataclass
class MappingReport:
    """Complete mapping resolution result.

    ``operations`` is authoritative.  ``decisions`` is its flattened
    compatibility representation, one decision per target field.
    """

    operations: list[MappingOperation] = field(default_factory=list)
    decisions: list[ExtendedMappingDecision] = field(default_factory=list)
    duplicate_targets: list[str] = field(default_factory=list)

    @property
    def unknown_headers(self) -> list[str]:
        return [
            d.original_header
            for d in self.decisions
            if d.method is MappingMethod.UNKNOWN
        ]

    @property
    def ambiguous_headers(self) -> list[str]:
        return [d.original_header for d in self.decisions if d.is_ambiguous]


def _multi_source_rules() -> list[dict[str, Any]]:
    return [
        rule
        for rule in STRUCTURAL_RULES
        if rule.get("mapping_mode") == "multi_source"
    ]


def resolve_headers(
    headers: list[str],
    manual_overrides: dict[str, str] | None = None,
) -> MappingReport:
    """Resolve source headers into deterministic mapping operations.

    Manual overrides are keyed by the verbatim source header and take precedence
    over all automatic rules.  Multi-source structural rules are then evaluated
    over the remaining headers, followed by single-column structural, alias,
    exact, and unknown resolution.
    """
    overrides = manual_overrides or {}
    header_infos = build_header_index(headers)
    remaining = list(header_infos)
    operations: list[MappingOperation] = []
    decisions: list[ExtendedMappingDecision] = []
    counter = 0

    def next_operation_id() -> str:
        nonlocal counter
        counter += 1
        return f"op-{counter:04d}"

    # 1. Manual overrides: source-column identity is the verbatim header.
    for info in header_infos:
        if info.original_name not in overrides:
            continue
        operation, operation_decisions = _resolve_manual(
            info, overrides[info.original_name], next_operation_id()
        )
        operations.append(operation)
        decisions.extend(operation_decisions)
        remaining.remove(info)

    # 2. Multi-column structural rules consume the matched source group as one
    # operation.  This is what makes SPLIT/INDICATOR mappings explicit.
    for rule in _multi_source_rules():
        matched = [
            info for info in remaining if info.normalized_name in rule["patterns"]
        ]
        if not matched:
            continue
        min_sources = int(rule.get("min_sources", 1))
        if len(matched) < min_sources:
            # Leave incomplete multi-column groups available to their ordinary
            # header-level rules.  This preserves existing single-column alias
            # behavior without silently inventing missing source columns.
            continue
        is_ambiguous = False
        ambiguity_note = None
        extractor, transformation = _structural_metadata(rule)
        targets = list(rule.get("targets") or [rule["target"]])
        operation, operation_decisions = _build_operation(
            operation_id=next_operation_id(),
            source_infos=matched,
            target_fields=targets,
            method=MappingMethod.STRUCTURAL,
            confidence=(
                _CONFIDENCE_STRUCTURAL_AMBIGUOUS
                if is_ambiguous
                else _CONFIDENCE_STRUCTURAL_UNAMBIGUOUS
            ),
            reason=(
                f"Structural rule '{rule['rule_type']}': "
                f"{rule.get('description', '')}"
            ),
            extractor=extractor,
            transformation=transformation,
            is_ambiguous=is_ambiguous,
            ambiguity_note=ambiguity_note,
        )
        operations.append(operation)
        decisions.extend(operation_decisions)
        for info in matched:
            remaining.remove(info)

    # 3. Resolve every remaining source column independently.
    for info in remaining:
        resolved, _ = _resolve_automatic(info, next_operation_id())
        for operation, operation_decisions in resolved:
            operations.append(operation)
            decisions.extend(operation_decisions)

    # Duplicate targets are conflicts between distinct mapping operations. A
    # fan-out operation deliberately produces several target decisions but is
    # not itself a duplicate mapping.
    target_operation_ids: dict[str, set[str]] = {}
    for operation in operations:
        for target in operation.target_fields:
            if target == "UNKNOWN":
                continue
            target_operation_ids.setdefault(target, set()).add(operation.operation_id)
    duplicate_targets = sorted(
        target for target, ids in target_operation_ids.items() if len(ids) > 1
    )

    # Preserve source-header order for downstream deterministic first-source
    # selection and quality-issue ordering, even though structural grouping was
    # resolved before independent columns.
    header_positions = {info.original_name: index for index, info in enumerate(header_infos)}
    operations.sort(
        key=lambda operation: min(
            header_positions.get(source, len(header_infos))
            for source in operation.source_columns
        )
    )
    decisions_by_operation: dict[str, list[ExtendedMappingDecision]] = {}
    for decision in decisions:
        decisions_by_operation.setdefault(decision.operation_id, []).append(decision)
    ordered_decisions = [
        decision
        for operation in operations
        for decision in decisions_by_operation.get(operation.operation_id, [])
    ]

    return MappingReport(
        operations=operations,
        decisions=ordered_decisions,
        duplicate_targets=duplicate_targets,
    )
