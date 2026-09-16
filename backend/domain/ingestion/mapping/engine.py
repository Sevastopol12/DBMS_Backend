"""Deterministic schema-mapping engine.

This module implements the authoritative, deterministic mapping layer of the
ingestion pipeline.

Responsibilities
----------------
* Accept a list of source headers (as strings).
* Normalize each header via :mod:`backend.domain.ingestion.header`.
* Resolve each normalized header to a canonical semantic field using the
  alias catalog in :mod:`.aliases`.
* Apply structural rules when a normalized header matches a rule pattern.
* Support manual override decisions that take unconditional precedence.
* Return an explicit :class:`~backend.domain.ingestion.contracts.MappingDecision`
  for every source header – including unknown and ambiguous ones.

Non-responsibilities
--------------------
* No cell-value transformation.
* No clinical-value validation.
* No LLM calls.
* No Celery, PostgreSQL, Redis, S3, or FastAPI dependencies.

Mapping method precedence (highest to lowest)
---------------------------------------------
1. MANUAL   – an explicit user-supplied override for a specific header
2. EXACT    – the normalized header exactly matches a canonical field name
3. ALIAS    – the normalized header is in the alias catalog
4. STRUCTURAL – the normalized header matches a structural rule pattern
5. HEURISTIC – (reserved for future fuzzy matching; not implemented here)
6. UNKNOWN  – no rule or alias matched

Confidence semantics
--------------------
EXACT      → 1.00  (the header *is* the canonical name)
MANUAL     → 1.00  (operator-supplied, unconditional)
ALIAS      → value from :data:`~.aliases.DIRECT_ALIASES` (0.35 – 1.00)
STRUCTURAL → 0.95 when the structural rule is unambiguous (one matching rule)
             0.70 when multiple structural rules match the same pattern
HEURISTIC  → (not produced by this engine in its current form)
UNKNOWN    → 0.00

Ambiguity handling
------------------
The engine never silently resolves an ambiguity.  Instead it marks the
decision with ``is_ambiguous=True`` and includes human-readable
``ambiguity_note`` text.  Callers must inspect this flag before relying on
``target_field``.

Structural decisions
--------------------
A structural decision is produced when the normalized header matches a
pattern in :data:`~.aliases.STRUCTURAL_RULES`.  Because one source column
can fan out to multiple target fields (e.g. the COMPOSITE blood-pressure
rule), :func:`resolve` returns *multiple* :class:`MappingDecision` objects
for such a column.  Callers should use ``source_columns`` to group decisions
that originate from the same source header.

Manual overrides
----------------
Pass a ``manual_overrides`` dict ``{original_header: canonical_field}`` to
:func:`resolve_headers`.  Overrides are applied before any other rule.  If an
override target is not a known canonical field the decision is still produced
with ``method=MANUAL`` but the ``ambiguity_note`` will mention that the
target is unrecognised.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.domain.ingestion.contracts import MappingDecision, MappingMethod
from backend.domain.ingestion.header import HeaderInfo, build_header_index

from .aliases import CANONICAL_FIELDS, DIRECT_ALIASES, STRUCTURAL_RULES

# ---------------------------------------------------------------------------
# Confidence constants
# ---------------------------------------------------------------------------
_CONFIDENCE_EXACT = 1.00
_CONFIDENCE_MANUAL = 1.00
_CONFIDENCE_STRUCTURAL_UNAMBIGUOUS = 0.95
_CONFIDENCE_STRUCTURAL_AMBIGUOUS = 0.70
_CONFIDENCE_UNKNOWN = 0.00

# Threshold below which a direct alias is surfaced as potentially ambiguous
_ALIAS_AMBIGUITY_THRESHOLD = 0.60


# ---------------------------------------------------------------------------
# Extended decision dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtendedMappingDecision:
    """A :class:`~backend.domain.ingestion.contracts.MappingDecision` plus
    ambiguity metadata that the contracts layer intentionally omits.

    Use :attr:`decision` to obtain the stable contract object.
    """

    original_header: str
    """Verbatim source header, preserved for diagnostics."""

    normalized_header: str
    """Normalized form of the header (output of the normalizer)."""

    target_field: str
    """Resolved canonical field name, or ``"UNKNOWN"`` when unresolved."""

    method: MappingMethod

    confidence: float

    reason: str | None = None
    """Human-readable explanation of why this mapping was chosen."""

    is_ambiguous: bool = False
    """True when the engine cannot determine a unique, high-confidence target."""

    ambiguity_note: str | None = None
    """Explanation of the ambiguity when ``is_ambiguous`` is True."""

    @property
    def decision(self) -> MappingDecision:
        """Return the stable contracts-layer representation."""
        return MappingDecision(
            source_columns=[self.original_header],
            target_field=self.target_field,
            method=self.method,
            confidence=self.confidence,
            reason=self.reason,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _structural_rules_for(normalized: str) -> list[dict]:
    """Return all structural rules whose ``patterns`` list contains *normalized*."""
    return [rule for rule in STRUCTURAL_RULES if normalized in rule["patterns"]]


def _resolve_one(
    header_info: HeaderInfo,
    manual_overrides: dict[str, str],
) -> list[ExtendedMappingDecision]:
    """Resolve a single :class:`HeaderInfo` to one or more decisions.

    Returns a *list* because a structural COMPOSITE rule can produce two
    decisions from one source column.
    """
    original = header_info.original_name
    normalized = header_info.normalized_name

    # ------------------------------------------------------------------
    # 1. MANUAL override
    # ------------------------------------------------------------------
    if manual_overrides.get(original, None) is not None:
        target = manual_overrides[original]
        unknown_target = target not in CANONICAL_FIELDS
        note = (
            f"Manual override target {target!r} is not a known canonical field."
            if unknown_target
            else None
        )
        return [
            ExtendedMappingDecision(
                original_header=original,
                normalized_header=normalized,
                target_field=target,
                method=MappingMethod.MANUAL,
                confidence=_CONFIDENCE_MANUAL,
                reason="Operator-supplied manual override.",
                is_ambiguous=unknown_target,
                ambiguity_note=note,
            )
        ]

    # ------------------------------------------------------------------
    # 2. EXACT match – normalized header is itself a canonical field name
    # ------------------------------------------------------------------
    if normalized in CANONICAL_FIELDS:
        return [
            ExtendedMappingDecision(
                original_header=original,
                normalized_header=normalized,
                target_field=normalized,
                method=MappingMethod.EXACT,
                confidence=_CONFIDENCE_EXACT,
                reason="Normalized header is itself a canonical field name.",
            )
        ]

    # ------------------------------------------------------------------
    # 3. ALIAS lookup
    # ------------------------------------------------------------------
    if normalized in DIRECT_ALIASES:
        entry = DIRECT_ALIASES[normalized]
        is_ambiguous = entry.confidence <= _ALIAS_AMBIGUITY_THRESHOLD
        note = (
            f"Alias confidence {entry.confidence:.2f} is at or below the ambiguity "
            f"threshold {_ALIAS_AMBIGUITY_THRESHOLD:.2f}; semantic meaning may differ."
            if is_ambiguous
            else None
        )
        return [
            ExtendedMappingDecision(
                original_header=original,
                normalized_header=normalized,
                target_field=entry.target,
                method=MappingMethod.ALIAS,
                confidence=entry.confidence,
                reason=f"Normalized alias {normalized!r} maps to {entry.target!r}.",
                is_ambiguous=is_ambiguous,
                ambiguity_note=note,
            )
        ]

    # ------------------------------------------------------------------
    # 4. STRUCTURAL rule match
    # ------------------------------------------------------------------
    matching_rules = _structural_rules_for(normalized)
    if matching_rules:
        ambiguous_structural = len(matching_rules) > 1

        confidence = (
            _CONFIDENCE_STRUCTURAL_AMBIGUOUS
            if ambiguous_structural
            else _CONFIDENCE_STRUCTURAL_UNAMBIGUOUS
        )
        note = (
            f"Normalized header {normalized!r} matches {len(matching_rules)} structural "
            "rules; target is uncertain."
            if ambiguous_structural
            else None
        )
        decisions: list[ExtendedMappingDecision] = []
        for rule in matching_rules:
            targets = rule.get("targets") or [rule["target"]]
            for target in targets:
                decisions.append(
                    ExtendedMappingDecision(
                        original_header=original,
                        normalized_header=normalized,
                        target_field=target,
                        method=MappingMethod.STRUCTURAL,
                        confidence=confidence,
                        reason=(
                            f"Structural rule '{rule['rule_type']}': "
                            f"{rule.get('description', '')}"
                        ),
                        is_ambiguous=ambiguous_structural,
                        ambiguity_note=note,
                    )
                )
        return decisions

    # ------------------------------------------------------------------
    # 5. UNKNOWN
    # ------------------------------------------------------------------
    return [
        ExtendedMappingDecision(
            original_header=original,
            normalized_header=normalized,
            target_field="UNKNOWN",
            method=MappingMethod.UNKNOWN,
            confidence=_CONFIDENCE_UNKNOWN,
            reason=f"No alias, canonical field, or structural rule matched {normalized!r}.",
            is_ambiguous=False,
        )
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class MappingReport:
    """Complete result of resolving a list of source headers.

    Attributes
    ----------
    decisions:
        One :class:`ExtendedMappingDecision` per resolved (source-column,
        target-field) pair.  A composite structural match produces multiple
        decisions for the same source column.
    duplicate_targets:
        Canonical field names that appear as the target of more than one
        decision (excluding UNKNOWN decisions).  Non-empty when two source
        columns both claim the same canonical field.
    """

    decisions: list[ExtendedMappingDecision] = field(default_factory=list)
    duplicate_targets: list[str] = field(default_factory=list)

    @property
    def unknown_headers(self) -> list[str]:
        """Original headers that could not be resolved."""
        return [
            d.original_header
            for d in self.decisions
            if d.method is MappingMethod.UNKNOWN
        ]

    @property
    def ambiguous_headers(self) -> list[str]:
        """Original headers flagged as ambiguous."""
        return [d.original_header for d in self.decisions if d.is_ambiguous]


def resolve_headers(
    headers: list[str],
    manual_overrides: dict[str, str] | None = None,
) -> MappingReport:
    """Resolve a list of raw source headers to a :class:`MappingReport`.

    Parameters
    ----------
    headers:
        Raw header strings as returned by the source reader
        (``SourceDataset.headers``).
    manual_overrides:
        Optional mapping of *original header string* → *canonical field name*.
        Overrides are applied before any automatic rule.

    Returns
    -------
    MappingReport
        Contains one :class:`ExtendedMappingDecision` for each
        (source-column, target-field) pair that was resolved.  Also includes
        a list of duplicate targets detected across the resolved decisions.

    Notes
    -----
    - The original header string is never mutated; it appears in every
      decision as ``original_header``.
    - UNKNOWN decisions are included so that callers have a complete picture
      of every source column's status.
    - Duplicate targets are reported but not resolved; callers must decide
      how to handle them.
    """
    overrides = manual_overrides or {}
    header_infos: list[HeaderInfo] = build_header_index(headers)

    all_decisions: list[ExtendedMappingDecision] = []
    for info in header_infos:
        all_decisions.extend(_resolve_one(info, overrides))

    # Detect duplicate semantic targets (UNKNOWN excluded)
    from collections import Counter

    target_counts = Counter(
        d.target_field for d in all_decisions if d.method is not MappingMethod.UNKNOWN
    )
    duplicate_targets = [t for t, count in target_counts.items() if count > 1]

    return MappingReport(decisions=all_decisions, duplicate_targets=duplicate_targets)
