"""Deliberately small, non-semantic text handling helpers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_header(name: str) -> str:
    if not name:
        return ""
    text: str = str(name).strip().lower()
    # Unlike accented vowels, "đ" does not NFD-decompose to an ASCII
    # base letter plus a combining mark.
    text = text.replace("đ", "d")
    # Decompose Unicode into base + combining marks
    text = unicodedata.normalize("NFD", text)
    # Drop combining marks (accents, diacritics)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    # Collapse separator runs into a single underscore
    text = re.compile(r"[^a-z0-9]+").sub("_", text)

    return text.strip("_")


def clean_optional_text(value: Any) -> str | None:
    """Return a trimmed string, treating null and whitespace-only input as empty.

    The caller must retain ``value`` in extraction lineage; this helper is only
    for the canonical value and never changes the traceable raw input.
    """
    if value is None:
        return None

    return str(value).strip() or None


def normalized_token(value: Any) -> str | None:
    """Normalize a short lexical token for explicit lookup tables only."""
    text = clean_optional_text(value)
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
