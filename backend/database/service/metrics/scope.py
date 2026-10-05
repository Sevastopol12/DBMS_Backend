from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class MetricsScope:
    kind: str
    facility_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"all", "rollup", "facility"}:
            raise ValueError("kind must be one of: all, rollup, facility")
        if self.kind == "facility" and self.facility_id is None:
            raise ValueError("facility scope requires facility_id")
        if self.kind != "facility" and self.facility_id is not None:
            raise ValueError(f"{self.kind} scope cannot have facility_id")

    @classmethod
    def all_facilities(cls) -> MetricsScope:
        return cls("all")

    @classmethod
    def rollup(cls) -> MetricsScope:
        return cls("rollup")

    @classmethod
    def facility(cls, facility_id: UUID) -> MetricsScope:
        return cls("facility", facility_id)

    @property
    def token(self) -> str:
        if self.kind == "facility":
            assert self.facility_id is not None
            return str(self.facility_id)
        return self.kind


__all__ = ["MetricsScope"]
