"""Deliberately small, non-semantic text handling helpers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _repair_mojibake(text: str) -> str:
    """Repair common UTF-8 bytes decoded once as Windows-1252.

    A number of deployed workbooks contain headers such as ``tÃ¢m`` and
    ``trÆ°Æ¡ng``.  Repairing those headers before lexical normalization keeps
    the cache matcher on the same alias keys without adding aliases to the
    runtime catalog.  Genuine Vietnamese text is left unchanged when the
    round-trip is not valid UTF-8.
    """
    encoded = bytearray()
    try:
        for char in text:
            try:
                encoded.extend(char.encode("cp1252"))
            except UnicodeEncodeError:
                # Some legacy decoding paths preserve undefined CP1252 bytes
                # as C1 controls (notably U+0081).  Keep their byte value.
                if 0x80 <= ord(char) <= 0x9F:
                    encoded.append(ord(char))
                else:
                    return text
        repaired = bytes(encoded).decode("utf-8")
    except UnicodeDecodeError:
        return text
    return repaired if repaired != text else text


def normalize_header(name: str) -> str:
    if not name:
        return ""
    text: str = _repair_mojibake(str(name).strip()).lower()
    text = text.replace("\u0111", "d").replace("\u00e4\u2018", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.compile(r"[^a-z0-9]+").sub("_", text)
    return text.strip("_")


def clean_optional_text(value: Any) -> str | None:
    """Return trimmed text, treating null and whitespace-only input as empty."""
    if value is None:
        return None
    return str(value).strip() or None


def normalized_token(value: Any) -> str | None:
    """Normalize a short lexical token for explicit lookup tables only."""
    text = clean_optional_text(value)
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFD", text.casefold())
    decomposed = decomposed.replace("\u0111", "d")
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


__all__ = ["normalize_header", "clean_optional_text", "normalized_token"]
