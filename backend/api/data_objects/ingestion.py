from pathlib import PurePath
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.api.data_objects.common import ApiDateTime
from backend.database.service.staging.schema import FileInfo
from backend.domain.processing.models import FileStatus


class IngestionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    content_type: str


class IngestionComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    content_hash: str
    size_bytes: int | None = None
    mappings: dict[str, Any] | None = None


class UploadReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_file_id: UUID
    filename: str
    content_type: str


class IngestionResponse(BaseModel):
    id: UUID
    facility_id: UUID
    filename: str | None = None
    object_key: str
    status: FileStatus

    presigned_url: str | None = None

    error_code: str | None = None
    error_message: str | None = None
    accepted_row_count: int = 0
    rejected_row_count: int = 0
    ignored_duplicate_row_count: int = 0

    parent_file_id: UUID | None = None
    rejection_report_available: bool = False
    rejection_report_expires_at: ApiDateTime | None = None

    created_at: ApiDateTime


class FileDetailResponse(BaseModel):
    id: UUID
    facility_id: UUID
    filename: str | None = None
    object_key: str | None = None
    status: FileStatus
    error_code: str | None = None
    error_message: str | None = None
    accepted_row_count: int = 0
    rejected_row_count: int = 0
    ignored_duplicate_row_count: int = 0
    parent_file_id: UUID | None = None
    rejection_report_available: bool = False
    rejection_report_expires_at: ApiDateTime | None = None
    created_at: ApiDateTime | None = None
    uploaded_at: ApiDateTime | None = None
    completed_at: ApiDateTime | None = None


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
    artifact_key = getattr(file, "rejection_artifact_key", None)
    artifact_expires = getattr(file, "rejection_artifact_expires_at", None)
    return IngestionResponse(
        id=file.id,
        facility_id=file.facility_id,
        filename=file.filename,
        object_key=file.object_key,
        status=file.status,
        presigned_url=presigned_url,
        accepted_row_count=file.accepted_row_count or 0,
        rejected_row_count=file.rejected_row_count or 0,
        ignored_duplicate_row_count=getattr(file, "ignored_duplicate_row_count", 0)
        or 0,
        parent_file_id=getattr(file, "parent_file_id", None),
        rejection_report_available=artifact_key is not None,
        rejection_report_expires_at=artifact_expires,
        error_code=file.error_code,
        error_message=file.error_message,
        created_at=file.created_at,
    )


def _serialize_file_detail(file: FileInfo) -> FileDetailResponse:
    artifact_key = getattr(file, "rejection_artifact_key", None)
    artifact_expires = getattr(file, "rejection_artifact_expires_at", None)
    return FileDetailResponse(
        id=file.id,
        facility_id=file.facility_id,
        filename=file.filename,
        object_key=file.object_key,
        status=file.status,
        error_code=file.error_code,
        error_message=file.error_message,
        accepted_row_count=file.accepted_row_count or 0,
        rejected_row_count=file.rejected_row_count or 0,
        ignored_duplicate_row_count=getattr(file, "ignored_duplicate_row_count", 0)
        or 0,
        parent_file_id=getattr(file, "parent_file_id", None),
        rejection_report_available=artifact_key is not None,
        rejection_report_expires_at=artifact_expires,
        created_at=file.created_at,
        uploaded_at=getattr(file, "uploaded_at", None),
        completed_at=getattr(file, "completed_at", None),
    )


__all__ = [
    "FileDetailResponse",
    "IngestionComplete",
    "IngestionCreate",
    "IngestionResponse",
    "UploadReportCreate",
    "_get_safe_filename",
    "_serialize_file_detail",
    "_serialize_ingestion",
]
