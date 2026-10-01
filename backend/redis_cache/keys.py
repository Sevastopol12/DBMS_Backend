from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

METRICS_CACHE_TTL_SECONDS = 3000
LAST_COMPUTED_AT_KEY = "metrics:last_computed_at"


def facility_scope(facility_id: UUID | str | None) -> str:
    """Return the cache scope token for a facility or the all-facilities rollup."""

    return "all" if facility_id is None else str(facility_id)


def period_summary_key(facility_id: UUID | str | None, grain: str) -> str:
    return f"metrics:period_summary:{facility_scope(facility_id)}:{grain}"


def comorbidity_key(facility_id: UUID | str | None, grain: str) -> str:
    return f"metrics:comorbidity:{facility_scope(facility_id)}:{grain}"


def out_of_control_key(facility_id: UUID | str | None) -> str:
    return f"metrics:patient_state:out_of_control:{facility_scope(facility_id)}"


def data_quality_key(facility_id: UUID | str | None, grain: str) -> str:
    return f"metrics:data_quality:{facility_scope(facility_id)}:{grain}"


def _sorted_rows(
    rows: Sequence[Mapping[str, Any]],
    fields: Sequence[tuple[str, bool]],
) -> list[dict[str, Any]]:
    """Sort copied rows, putting missing values last for every sort field.

    Applying stable sorts from the least significant field to the most
    significant field preserves ties and gives the same result as a SQL
    ``ORDER BY ... NULLS LAST`` clause without mutating the input sequence.
    """

    ordered = [dict(row) for row in rows]
    for field, reverse in reversed(fields):
        present = [row for row in ordered if row.get(field) is not None]
        missing = [row for row in ordered if row.get(field) is None]
        present.sort(key=lambda row: row[field], reverse=reverse)
        ordered = present + missing
    return ordered


def sort_period_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _sorted_rows(rows, (("period_start", False), ("facility_id", False)))


def sort_comorbidity(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _sorted_rows(
        rows,
        (
            ("period_start", False),
            ("diagnosis_label", False),
            ("facility_id", False),
        ),
    )


def sort_out_of_control(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _sorted_rows(
        rows,
        (
            ("is_bp_crisis", True),
            ("last_visit_date", True),
            ("patient_key", False),
        ),
    )


def sort_data_quality(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _sorted_rows(rows, (("period_start", False), ("facility_id", False)))


__all__ = [
    "LAST_COMPUTED_AT_KEY",
    "METRICS_CACHE_TTL_SECONDS",
    "comorbidity_key",
    "data_quality_key",
    "facility_scope",
    "out_of_control_key",
    "period_summary_key",
    "sort_comorbidity",
    "sort_data_quality",
    "sort_out_of_control",
    "sort_period_summary",
]
