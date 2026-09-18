"""Readers that turn uploaded tabular files into source-domain datasets."""

from .base import SourceDatasetReader
from .errors import (
    CorruptFileError,
    EmptyFileError,
    EmptyWorksheetError,
    ReaderError,
    UnreadableInputError,
    UnsupportedDelimiterError,
    UnsupportedFormatError,
)
from .tabular import TabularSourceReader, read_source_dataset

__all__ = [
    "CorruptFileError",
    "EmptyFileError",
    "EmptyWorksheetError",
    "ReaderError",
    "SourceDatasetReader",
    "TabularSourceReader",
    "UnreadableInputError",
    "UnsupportedDelimiterError",
    "UnsupportedFormatError",
    "read_source_dataset",
]
