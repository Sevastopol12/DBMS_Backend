from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable

from ...models import ColumnMap, MappingOperation
from ...transformation.normalization import normalize_header

if TYPE_CHECKING:
    from ..source.snapshot import MappingSource


@dataclass(frozen=True)
class MappingEntry:
    alias: str
    concept: str
    operation: MappingOperation
    output_targets: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    curated: bool = True
    requires_profile: bool = False

    @property
    def normalized_alias(self) -> str:
        return normalize_header(self.alias)


@dataclass(frozen=True)
class ResolvedHeader:
    source: ColumnMap
    entry: MappingEntry
    score: float
    resolution: str


@dataclass(frozen=True)
class MatchAttempt:
    """The result of the authoritative cache-backed header matcher."""

    source: ColumnMap
    entry: MappingEntry | None
    score: float
    resolution: str

    @property
    def matched(self) -> bool:
        return self.entry is not None


class MappingCatalog:
    """Supporting metadata index for the authoritative mapping matcher."""

    def __init__(
        self,
        entries: Iterable[MappingEntry] = (),
        *,
        cache_client: MappingSource | None = None,
    ) -> None:
        self.entries = tuple(entries)
        self.cache_client = cache_client

    @classmethod
    def for_task(
        cls,
        cache_client: MappingSource | None = None,
    ) -> "MappingCatalog":
        return cls((), cache_client=cache_client)

    @staticmethod
    def _target_definition(
        target: str,
    ) -> tuple[str, MappingOperation, tuple[str, ...]] | None:
        """Return semantics for a cache target, including legacy composites."""
        normalized = normalize_header(target)
        if normalized == "chi_so_huyet_ap":
            return (
                "blood_pressure",
                MappingOperation.SPLIT_BLOOD_PRESSURE,
                ("huyet_ap_tam_thu", "huyet_ap_tam_truong"),
            )
        if normalized in {"chi_so_icd_tha_dtd", "chi_so_icd_dtd_tha"}:
            return (
                "icd",
                MappingOperation.SPLIT_ICD,
                ("icd_tha", "icd_dtd", "chan_doan_di_kem"),
            )
        return None

    def entry_for_target(
        self, source: ColumnMap, target: str, tier: str | None = None
    ) -> MappingEntry:
        """Build operation metadata for a target returned by the cache."""
        target = target.strip()
        if normalize_header(target) == "dia_chi" and tier is not None and tier.upper() == "DYNAMIC":
            return MappingEntry(
                alias=source.original_name,
                concept="address_component",
                operation=MappingOperation.CONCAT,
                output_targets=("dia_chi",),
                metadata={"separator": ", "},
                curated=False,
            )
        definition = self._target_definition(target)
        if definition is not None:
            concept, operation, output_targets = definition
            return MappingEntry(
                alias=source.original_name,
                concept=concept,
                operation=operation,
                output_targets=output_targets,
                curated=False,
            )

        normalized = normalize_header(target)
        if normalized == "gioi_tinh":
            concept = "gender"
        elif normalized in {"icd_tha", "icd_dtd"}:
            concept = normalized
        else:
            concept = "cache"
        return MappingEntry(
            alias=source.original_name,
            concept=concept,
            operation=MappingOperation.DIRECT,
            output_targets=(target,),
            curated=False,
        )

    def entry_for_explicit(
        self, source: ColumnMap, explicit: Any
    ) -> MappingEntry | None:
        if isinstance(explicit, dict):
            target = explicit.get(
                "target_field", explicit.get("mapping_target", explicit.get("target"))
            )
            operation_value = explicit.get("operation")
            output_targets = explicit.get("output_targets")
            metadata = explicit.get("metadata", {})
        else:
            target = explicit
            operation_value = None
            output_targets = None
            metadata = {}
        if not isinstance(target, str) or not target.strip():
            return None
        semantic = self.entry_for_target(source, target)
        if operation_value is None and not output_targets:
            return semantic
        try:
            operation = (
                MappingOperation(operation_value)
                if operation_value
                else semantic.operation
            )
        except (TypeError, ValueError):
            return None
        targets = tuple(output_targets) if output_targets else semantic.output_targets
        return MappingEntry(
            alias=source.original_name,
            concept="explicit",
            operation=operation,
            output_targets=targets,
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
            curated=False,
        )


__all__ = [
    "MappingCatalog",
    "MappingEntry",
    "MatchAttempt",
    "ResolvedHeader",
]
