from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


class LoginResponse(BaseModel):
    session_token: str
    facility_id: UUID


__all__ = ["LoginRequest", "LoginResponse"]
