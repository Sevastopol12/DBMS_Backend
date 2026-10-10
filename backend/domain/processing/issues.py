from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Issue:
    severity: Literal["INVALID"]
    code: str


__all__ = ["Issue"]
