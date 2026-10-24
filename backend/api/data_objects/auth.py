from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.api.data_objects.common import ApiDateTime


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


class LoginResponse(BaseModel):
    session_token: str
    refresh_token: str
    facility_id: UUID
    access_expires_at: ApiDateTime
    refresh_expires_at: ApiDateTime
    session_expires_at: ApiDateTime


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class RefreshResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_token: str
    refresh_token: str
    access_expires_at: ApiDateTime
    refresh_expires_at: ApiDateTime
    session_expires_at: ApiDateTime


__all__ = ["LoginRequest", "LoginResponse", "RefreshRequest", "RefreshResponse"]
