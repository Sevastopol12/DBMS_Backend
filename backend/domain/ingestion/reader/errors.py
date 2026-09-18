"""Domain errors raised while reading uploaded source files."""


class ReaderError(Exception):
    """Base class for expected source-reader failures."""


class UnsupportedFormatError(ReaderError):
    """The filename does not identify a supported tabular format."""


class UnreadableInputError(ReaderError):
    """Input cannot be decoded or otherwise accessed as the claimed format."""


class CorruptFileError(ReaderError):
    """Input is structurally invalid for its claimed format."""


class EmptyFileError(ReaderError):
    """A CSV has no usable contents."""


class EmptyWorksheetError(ReaderError):
    """The selected XLSX worksheet has no rows."""


class UnsupportedDelimiterError(ReaderError):
    """CSV input appears to use a delimiter other than a comma."""
