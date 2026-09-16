"""Header normalization for the ingestion pipeline.

Normalization is a deterministic, lossless transformation that produces a
stable identifier from an arbitrary source header string.  The original
header is always preserved alongside the normalized form so that every
downstream stage can refer to either representation without round-tripping
through the normalizer.

Public surface
--------------
- :func:`normalize` – Normalize a single header string.
- :class:`HeaderInfo` – Value-object that pairs an original header with its
  normalized form.
- :func:`build_header_index` – Build a list of :class:`HeaderInfo` from a
  raw header list (as produced by the source reader).
"""

from __future__ import annotations

from .normalizer import HeaderInfo, build_header_index, normalize

__all__ = [
    "HeaderInfo",
    "build_header_index",
    "normalize",
]
