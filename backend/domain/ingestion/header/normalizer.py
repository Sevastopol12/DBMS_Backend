"""Deterministic header normalizer.

Normalization pipeline
----------------------
1. Strip leading/trailing whitespace.
2. Lowercase.
3. NFD-decompose Unicode to separate base characters from combining marks.
4. Remove all combining marks (category "Mn") – this strips accents and
   diacritics from Vietnamese and other languages.
5. Transliterate Vietnamese ``Đ``/``đ`` to ``d``. These letters do not
   decompose under NFD, so they require an explicit deterministic mapping.
6. Replace every run of non-alphanumeric characters with a single underscore
   (this converts spaces, hyphens, slashes, dots, etc.).
7. Strip any leading or trailing underscores that remain.

This is the same algorithm that is already used in
``backend.domain.utils.normalize_column_name`` and is reproduced here so
that the header package is independently importable without pulling in the
broader utils module.

The original header string is never mutated; :class:`HeaderInfo` keeps both
representations.

Examples
--------
>>> normalize("HỌ VÀ TÊN")
'ho_va_ten'
>>> normalize("Họ và tên ")
'ho_va_ten'
>>> normalize("Ho_va_Ten")
'ho_va_ten'
>>> normalize("Họ-Và-Tên")
'ho_va_ten'
>>> normalize("CMND/CCCD")
'cmnd_cccd'
>>> normalize("Năm sinh")
'nam_sinh'
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(header: object) -> str:
    """Return the normalized form of *header*.

    Always returns a ``str``.  An empty or non-string input returns an empty
    string rather than raising, so callers can safely normalize untrusted
    input and then check for emptiness.
    """
    if not header:
        return ""
    text: str = str(header).strip().lower()
    # Unlike accented vowels, "đ" does not NFD-decompose to an ASCII
    # base letter plus a combining mark.
    text = text.replace("đ", "d")
    # Decompose Unicode into base + combining marks
    text = unicodedata.normalize("NFD", text)
    # Drop combining marks (accents, diacritics)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    # Collapse separator runs into a single underscore
    text = _NON_ALNUM.sub("_", text)
    return text.strip("_")


@dataclass(frozen=True, slots=True)
class HeaderInfo:
    """Immutable pairing of an original source header with its normalized form.

    Both fields are always populated.  :attr:`original_name` is the verbatim
    string as it appeared in the source file; :attr:`normalized_name` is the
    result of running :func:`normalize` on that string.
    """

    original_name: str
    normalized_name: str = field(init=False)

    def __post_init__(self) -> None:
        # frozen=True prevents normal attribute assignment; use object.__setattr__
        object.__setattr__(self, "normalized_name", normalize(self.original_name))

    def __repr__(self) -> str:
        return (
            f"HeaderInfo(original_name={self.original_name!r}, "
            f"normalized_name={self.normalized_name!r})"
        )


def build_header_index(headers: list[str]) -> list[HeaderInfo]:
    """Convert a list of raw header strings into a list of :class:`HeaderInfo`.

    The order is preserved so that the resulting list can be zipped with any
    positional column structure (e.g. from the source reader).

    Parameters
    ----------
    headers:
        Raw header strings as returned by the source reader, e.g.
        ``SourceDataset.headers``.

    Returns
    -------
    list[HeaderInfo]
        One :class:`HeaderInfo` per element of *headers*, in the same order.
    """
    return [HeaderInfo(original_name=h) for h in headers]
