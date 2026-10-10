from __future__ import annotations

from typing import Any

RESERVED_PREFIX = "_dbms_"
COL_ORIGIN_FILE = "_dbms_origin_file_id"
COL_ORIGIN_ROW = "_dbms_origin_row"
COL_ISSUES = "_dbms_issue_codes"
COL_INVALID_FIELDS = "_dbms_invalid_fields"
COL_DUP_ROLE = "_dbms_duplicate_role"
COL_MERGED_INTO = "_dbms_merged_into_row"
COL_GROUP_ROWS = "_dbms_group_rows"


def strip_reserved(
    headers: list[str], rows: list[dict[str, Any]]
) -> tuple[list[str], list[dict[str, Any]]]:
    kept = [
        header
        for header in headers
        if not header.casefold().startswith(RESERVED_PREFIX)
    ]
    excluded = set(headers) - set(kept)
    return kept, [
        {key: value for key, value in row.items() if key not in excluded}
        for row in rows
    ]


__all__ = [
    "COL_DUP_ROLE",
    "COL_GROUP_ROWS",
    "COL_INVALID_FIELDS",
    "COL_ISSUES",
    "COL_MERGED_INTO",
    "COL_ORIGIN_FILE",
    "COL_ORIGIN_ROW",
    "RESERVED_PREFIX",
    "strip_reserved",
]
