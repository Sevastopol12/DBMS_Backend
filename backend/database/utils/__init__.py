from pathlib import PurePath
from backend.domain.models import IngestionResponse
from backend.database.schema import FileInfo


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
