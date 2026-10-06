class DatabaseServiceError(Exception):
    pass


class DuplicatedContentError(DatabaseServiceError):
    pass


class FileObjectNotFound(DatabaseServiceError):
    pass


class StorageUnavailable(DatabaseServiceError):
    """The source object store could not be reached or returned an error."""


class MetricsRunInProgress(DatabaseServiceError):
    pass


class MetricsStoreUnavailable(DatabaseServiceError):
    pass


CONTENT_HASH_UNIQUE_CONSTRAINT = "ingestion_files_facility_hash_unique"
COMPUTATION_RUN_SINGLE_RUNNING_INDEX = "computation_run_log_single_running"


def is_duplicate_content_integrity_error(error: BaseException) -> bool:
    """Identify the declared content-hash constraint without parsing messages."""
    original = getattr(error, "orig", error)
    diagnostics = getattr(original, "diag", None)
    return (
        getattr(diagnostics, "constraint_name", None) == CONTENT_HASH_UNIQUE_CONSTRAINT
    )


def is_run_in_progress_integrity_error(error: BaseException) -> bool:
    """Identify the single-running computation constraint without parsing messages."""
    original = getattr(error, "orig", error)
    diagnostics = getattr(original, "diag", None)
    return (
        getattr(diagnostics, "constraint_name", None)
        == COMPUTATION_RUN_SINGLE_RUNNING_INDEX
    )


__all__ = [
    "COMPUTATION_RUN_SINGLE_RUNNING_INDEX",
    "CONTENT_HASH_UNIQUE_CONSTRAINT",
    "DuplicatedContentError",
    "FileObjectNotFound",
    "MetricsRunInProgress",
    "MetricsStoreUnavailable",
    "StorageUnavailable",
    "is_duplicate_content_integrity_error",
    "is_run_in_progress_integrity_error",
]
