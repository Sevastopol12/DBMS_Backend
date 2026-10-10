from typing import Literal

from pydantic import BaseModel


class HealthStatusResponse(BaseModel):
    status: Literal["ok"]


__all__ = ["HealthStatusResponse"]
