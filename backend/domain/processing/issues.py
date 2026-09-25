from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Issue:
    severity: Literal["INVALID", "SUSPICIOUS"]
    code: str


__all__ = ["Issue"]
