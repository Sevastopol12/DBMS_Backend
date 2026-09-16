"""Deliberately small, non-semantic text handling helpers."""

from __future__ import annotations

import unicodedata
from typing import Any


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
