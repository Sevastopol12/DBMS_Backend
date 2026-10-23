from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from backend.api.data_objects.common import ApiDateTime


class _OutboundFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricsUpdated(_OutboundFrame):
    type: Literal["metrics.updated"] = "metrics.updated"
    facility_id: UUID
    computed_at: ApiDateTime


class SessionExpiring(_OutboundFrame):
    type: Literal["session.expiring"] = "session.expiring"
    expires_in: int


class SessionRefreshed(_OutboundFrame):
    type: Literal["session.refreshed"] = "session.refreshed"
    session_token: str
    refresh_token: str
    access_expires_at: ApiDateTime
    refresh_expires_at: ApiDateTime


class ProtocolError(_OutboundFrame):
    type: Literal["error"] = "error"
    code: Literal["refresh_invalid", "unavailable"]
    message: str


class SessionRefresh(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["session.refresh"]
    refresh_token: str


class MetricsUpdatedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    facility_id: UUID
    computed_at: datetime


IncomingFrame = Annotated[SessionRefresh, Field(discriminator="type")]
OutgoingFrame = Annotated[
    MetricsUpdated | SessionExpiring | SessionRefreshed | ProtocolError,
    Field(discriminator="type"),
]
INCOMING_FRAME_ADAPTER = TypeAdapter(IncomingFrame)
OUTGOING_FRAME_ADAPTER = TypeAdapter(OutgoingFrame)

__all__ = [
    "INCOMING_FRAME_ADAPTER",
    "OUTGOING_FRAME_ADAPTER",
    "IncomingFrame",
    "MetricsUpdated",
    "MetricsUpdatedPayload",
    "OutgoingFrame",
    "ProtocolError",
    "SessionExpiring",
    "SessionRefresh",
    "SessionRefreshed",
]
