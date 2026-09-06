class DatabaseError(Exception):
    pass


class FileDuplicatedError(DatabaseError):
    def __init__(self, filename: str, file_hash: str):
        super().__init__(f"File {filename} containing [{file_hash}] already recorded.")


__all__ = ["FileDuplicatedError"]
