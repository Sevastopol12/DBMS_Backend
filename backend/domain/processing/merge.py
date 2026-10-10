from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from backend.database.canonical import (
    CANONICAL_FIELDS,
    IDENTITY_FIELDS,
    CanonicalField,
)

from .transformation.validation import ValidationState


@dataclass(frozen=True)
class FieldCandidate:
    value: Any
    state: ValidationState
    issue_code: str | None = None


@dataclass(frozen=True)
class RowCandidate:
    row_number: int
    fields: Mapping[str, FieldCandidate]


@dataclass(frozen=True)
class MergedGroup:
    values: dict[str, Any]
    states: dict[str, ValidationState]
    field_issues: dict[str, str]
    supplied_by: dict[str, int]


def merge_candidates(
    cands: Sequence[RowCandidate],
    specs: Sequence[CanonicalField] = CANONICAL_FIELDS,
) -> MergedGroup:
    if not cands:
        raise ValueError("cannot merge an empty candidate group")
    values: dict[str, Any] = {}
    states: dict[str, ValidationState] = {}
    field_issues: dict[str, str] = {}
    supplied_by: dict[str, int] = {}
    for spec in specs:
        name = spec.name
        field_candidates = [
            candidate.fields[name] for candidate in cands if name in candidate.fields
        ]
        if name in IDENTITY_FIELDS:
            valid = [
                (candidate.row_number, candidate.fields[name])
                for candidate in cands
                if name in candidate.fields
                and candidate.fields[name].state is ValidationState.VALID
            ]
            if valid:
                # Group key semantics: every member of a real group shares
                # the same key, so the first VALID row defines the group.
                supplied_by[name], chosen = valid[0]
            elif any(
                item.state is ValidationState.MISSING for item in field_candidates
            ):
                values[name] = None
                states[name] = ValidationState.MISSING
                continue
            elif field_candidates:
                supplied_by[name], chosen = next(
                    (candidate.row_number, candidate.fields[name])
                    for candidate in reversed(cands)
                    if name in candidate.fields
                )
            else:
                values[name] = None
                states[name] = ValidationState.MISSING
                continue
        else:
            valid = [
                (candidate.row_number, candidate.fields[name])
                for candidate in cands
                if name in candidate.fields
                and candidate.fields[name].state is ValidationState.VALID
            ]
            if valid:
                supplied_by[name], chosen = valid[-1]
            elif any(
                item.state is ValidationState.MISSING for item in field_candidates
            ):
                values[name] = None
                states[name] = ValidationState.MISSING
                continue
            elif field_candidates:
                supplied_by[name], chosen = next(
                    (candidate.row_number, candidate.fields[name])
                    for candidate in reversed(cands)
                    if name in candidate.fields
                )
            else:
                values[name] = None
                states[name] = ValidationState.MISSING
                continue
        values[name] = chosen.value if chosen.state is ValidationState.VALID else None
        states[name] = chosen.state
        if chosen.issue_code:
            field_issues[name] = chosen.issue_code
        supplied_by.setdefault(name, cands[0].row_number)
    return MergedGroup(values, states, field_issues, supplied_by)


__all__ = ["FieldCandidate", "MergedGroup", "RowCandidate", "merge_candidates"]
