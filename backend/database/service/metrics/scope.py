from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class MetricsScope:
    """Per-facility metrics scope (D-10)."""

    facility_id: UUID

    @classmethod
    def facility(cls, facility_id: UUID) -> MetricsScope:
        return cls(facility_id)

    @property
    def token(self) -> str:
        return str(self.facility_id)


__all__ = ["MetricsScope"]
