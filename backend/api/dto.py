from datetime import datetime
from pathlib import PurePath
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from backend.database.service.staging.schema import FileInfo
from backend.domain.processing.models import FileStatus


class IngestionCreate(BaseModel):
    filename: str
    content: str | None = None
    content_type: str


class IngestionComplete(BaseModel):
    id: UUID
    content_hash: str
    size_bytes: int | None = None
    mappings: dict[str, Any] | None = None


class IngestionResponse(BaseModel):
    id: UUID
    filename: str | None = None
    object_key: str
    status: FileStatus

    presigned_url: str | None = None

    error_code: str | None = None
    error_message: str | None = None
    accepted_row_count: int = 0
    rejected_row_count: int = 0

    created_at: datetime


def _get_safe_filename(filename: str) -> str:
    name = PurePath(filename).name
    if not name or name in {".", ".."}:
        raise ValueError("A valid filename is required")
    return "".join(
        character if character.isalnum() or character in ".-_" else "_"
        for character in name
    )


def _serialize_ingestion(
    file: FileInfo, presigned_url: str | None = None
) -> IngestionResponse:
    return IngestionResponse(
        id=file.id,
        filename=file.filename,
        object_key=file.object_key,
        status=file.status,
        presigned_url=presigned_url,
        accepted_row_count=file.accepted_row_count,
        rejected_row_count=file.rejected_row_count,
        error_code=file.error_code,
        error_message=file.error_message,
        created_at=file.created_at,
    )


__all__ = [
    "IngestionCreate",
    "IngestionComplete",
    "IngestionResponse",
    "_get_safe_filename",
    "_serialize_ingestion",
]
