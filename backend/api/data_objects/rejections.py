from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.api.data_objects.common import ApiDateTime


class RejectionDownloadResponse(BaseModel):
    url: str
    expires_in_seconds: int
    filename: str


class RejectedArtifactItem(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    file_id: UUID
    filename: str
    parent_file_id: UUID | None = None
    file_status: str
    state: Literal["available", "expired"]
    artifact_created_at: ApiDateTime | None = None
    artifact_expires_at: ApiDateTime | None = None
    rejected_row_count: int = 0


class RejectedArtifactListResponse(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    items: list[RejectedArtifactItem]
    next_cursor: str | None = None
    limit: int


class RejectedArtifactDownload(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    file_id: UUID
    download_url: str
    artifact_filename: str
    url_expires_at: ApiDateTime


__all__ = [
    "RejectedArtifactDownload",
    "RejectedArtifactItem",
    "RejectedArtifactListResponse",
    "RejectionDownloadResponse",
]
