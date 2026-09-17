"""Deterministic schema-mapping layer for the ingestion pipeline.

Public surface
--------------
- :func:`resolve_headers` – Map a list of raw source headers to an
  authoritative :class:`MappingReport`.
- :class:`MappingReport` – Complete resolution result with operations and decisions,
  unknown headers, ambiguous headers, and duplicate-target detection.
- :class:`ExtendedMappingDecision` – Per-column mapping decision, including
  original header, normalized header, target field, method, confidence,
  and ambiguity metadata.
- :data:`DIRECT_ALIASES` – Read-only view of the canonical alias catalog.
- :data:`STRUCTURAL_RULES` – Read-only list of structural mapping rules.
- :data:`CANONICAL_FIELDS` – Frozenset of all known canonical field names.
"""

from __future__ import annotations

from .aliases import CANONICAL_FIELDS, DIRECT_ALIASES, EXTRACTOR_RULES, STRUCTURAL_RULES, AliasEntry
from .engine import ExtendedMappingDecision, MappingReport, resolve_headers

__all__ = [
    "AliasEntry",
    "CANONICAL_FIELDS",
    "DIRECT_ALIASES",
    "EXTRACTOR_RULES",
    "STRUCTURAL_RULES",
    "ExtendedMappingDecision",
    "MappingReport",
    "resolve_headers",
]
