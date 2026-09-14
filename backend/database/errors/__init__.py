class DatabaseServiceError(Exception):
    pass


class DuplicatedContentError(DatabaseServiceError):
    pass


class FileObjectNotFound(DatabaseServiceError):
    pass


__all__ = ["DuplicatedContentError", "FileObjectNotFound"]
