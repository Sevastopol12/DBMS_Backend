from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from enum import Enum


class FileStatus(str, Enum):
    CREATED: str = "CREATED"
    QUEUED: str = "QUEUED"
    PROCESSING: str = "PROCESSING"
    SUCCEED: str = "SUCCEED"
    ERROR: str = "ERROR"


class IngestionCreate(BaseModel):
    filename: str
    content: str | None = None
    content_type: str


class IngestionComplete(BaseModel):
    id: UUID
    content_hash: str
    size_bytes: int
    mappings: dict[str, str] | None = None


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


class MappingRequest(BaseModel):
    filename: str
    columns: list[str]


class MappingResponse(BaseModel):
    filename: str
    mapping: dict[str, str | None] | None = None
