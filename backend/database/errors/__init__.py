class DatabaseServiceError(Exception):
    pass


class FileObjectNotFound(DatabaseServiceError):
    pass


class StorageUnavailable(DatabaseServiceError):
    """The source object store could not be reached or returned an error."""


class MetricsRunInProgress(DatabaseServiceError):
    pass


class MetricsStoreUnavailable(DatabaseServiceError):
    pass


class MetricsDataIntegrityError(DatabaseServiceError):
    """Persisted metric rows failed DTO validation (data-quality problem)."""


COMPUTATION_RUN_SINGLE_RUNNING_INDEX = "computation_run_log_single_running"


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
    "FileObjectNotFound",
    "MetricsDataIntegrityError",
    "MetricsRunInProgress",
    "MetricsStoreUnavailable",
    "StorageUnavailable",
    "is_run_in_progress_integrity_error",
]
