class DatabaseServiceError(Exception):
    pass


class DuplicatedContentError(DatabaseServiceError):
    pass


class FileObjectNotFound(DatabaseServiceError):
    pass


class StorageUnavailable(DatabaseServiceError):
    """The source object store could not be reached or returned an error."""

    pass


CONTENT_HASH_UNIQUE_CONSTRAINT = "ingestion_files_content_hash_unique"


def is_duplicate_content_integrity_error(error: BaseException) -> bool:
    """Identify the declared content-hash constraint without parsing messages."""
    original = getattr(error, "orig", error)
    diagnostics = getattr(original, "diag", None)
    return getattr(diagnostics, "constraint_name", None) == CONTENT_HASH_UNIQUE_CONSTRAINT


__all__ = [
    "CONTENT_HASH_UNIQUE_CONSTRAINT",
    "DuplicatedContentError",
    "FileObjectNotFound",
    "StorageUnavailable",
    "is_duplicate_content_integrity_error",
]
