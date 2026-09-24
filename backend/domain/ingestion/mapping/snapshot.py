from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Iterator, Protocol

from backend.domain.models import CacheSource, HeaderMapValue


logger = logging.getLogger(__name__)


class MappingSourceKind(str, Enum):
    REDIS = "REDIS"
    DB = "DB"
    NONE = "NONE"


class MappingSourceUnavailable(RuntimeError):
    """Raised when no mapping source is available for a lookup."""


class MappingSource(Protocol):
    kind: MappingSourceKind

    def get_column_cache(self, name: str) -> HeaderMapValue | None:
        ...

    def iter_mapping_keys(self) -> Iterator[str]:
        ...


@dataclass
class MappingSnapshot:
    direct: dict[str, str]
    dynamic: dict[str, str]
    kind: MappingSourceKind

    def __post_init__(self) -> None:
        self.direct = dict(self.direct)
        self.dynamic = dict(self.dynamic)

    def get_column_cache(self, name: str) -> HeaderMapValue | None:
        name = name.lower()
        if name in self.direct:
            return HeaderMapValue(value=self.direct[name], cache_key=CacheSource.DIRECT)
        if name in self.dynamic:
            return HeaderMapValue(value=self.dynamic[name], cache_key=CacheSource.DYNAMIC)
        return None

    def iter_mapping_keys(self) -> Iterator[str]:
        yield from self.direct
        yield from self.dynamic

    @property
    def is_complete(self) -> bool:
        return bool(self.direct) and bool(self.dynamic)

    @classmethod
    def from_redis_hashes(
        cls,
        direct_raw: dict[bytes | str, bytes | str],
        dynamic_raw: dict[bytes | str, bytes | str],
    ) -> "MappingSnapshot":
        return cls(
            direct=cls._decode_hash(direct_raw),
            dynamic=cls._decode_hash(dynamic_raw),
            kind=MappingSourceKind.REDIS,
        )

    @classmethod
    def from_rows(cls, rows: Iterable[object]) -> "MappingSnapshot":
        values: dict[str, dict[str, set[str]]] = {
            CacheSource.DIRECT.value: {},
            CacheSource.DYNAMIC.value: {},
        }
        for row in rows:
            alias = getattr(row, "normalized_alias", "")
            tier = getattr(row, "tier", "")
            target = getattr(row, "target", "")
            if not isinstance(alias, str) or not isinstance(tier, str) or not isinstance(target, str):
                continue
            alias = alias.strip()
            tier = tier.strip().upper()
            target = target.strip()
            if not alias or tier not in values or not target:
                continue
            values[tier].setdefault(alias, set()).add(target)

        mappings: dict[str, dict[str, str]] = {}
        for tier, aliases in values.items():
            mappings[tier] = {}
            for alias, targets in aliases.items():
                if len(targets) > 1:
                    logger.warning(
                        "Dropping conflicting mapping alias %r for tier %s",
                        alias,
                        tier,
                    )
                    continue
                mappings[tier][alias] = next(iter(targets))
        return cls(
            direct=mappings[CacheSource.DIRECT.value],
            dynamic=mappings[CacheSource.DYNAMIC.value],
            kind=MappingSourceKind.DB,
        )

    @staticmethod
    def _decode_hash(raw: dict[bytes | str, bytes | str]) -> dict[str, str]:
        decoded: dict[str, str] = {}
        for key, value in raw.items():
            key_text = MappingSnapshot._decode_text(key)
            value_text = MappingSnapshot._decode_text(value)
            if key_text is None or value_text is None or not key_text or not value_text:
                continue
            decoded[key_text] = value_text
        return decoded

    @staticmethod
    def _decode_text(value: bytes | str) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return None
        return None


class UnavailableMappingSource:
    kind = MappingSourceKind.NONE

    def get_column_cache(self, name: str) -> HeaderMapValue | None:
        del name
        raise MappingSourceUnavailable("Mapping source unavailable")

    def iter_mapping_keys(self) -> Iterator[str]:
        raise MappingSourceUnavailable("Mapping source unavailable")


__all__ = [
    "MappingSourceKind",
    "MappingSourceUnavailable",
    "MappingSource",
    "MappingSnapshot",
    "UnavailableMappingSource",
]
