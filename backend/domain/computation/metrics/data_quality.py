"""Quality-report aggregates for ingestion files."""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime
from typing import Any

import pandas as pd


def _quality_report(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def _number(report: dict[str, Any], field: str) -> int:
    try:
        return int(report.get(field) or 0)
    except (TypeError, ValueError):
        return 0


def compute_data_quality(
    files: pd.DataFrame,
    *,
    facility_id: Any = None,
    period_grain: str | None = None,
    period_start: datetime | pd.Timestamp | None = None,
    period_end: datetime | pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Aggregate the quality-report JSON objects in one bucket."""

    reports = [_quality_report(value) for value in files.get("quality_report", [])]
    coverage = []
    issue_counts: Counter[str] = Counter()
    for report in reports:
        try:
            ratio = report.get("coverage_ratio")
            if ratio is not None:
                parsed = float(ratio)
                if math.isfinite(parsed):
                    coverage.append(parsed)
        except (TypeError, ValueError):
            pass
        raw_issues = report.get("issue_code_counts") or {}
        if isinstance(raw_issues, dict):
            for code, count in raw_issues.items():
                try:
                    issue_counts[str(code)] += int(count)
                except (TypeError, ValueError):
                    continue
    top_issues = [
        {"code": code, "count": count}
        for code, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    ]
    return {
        "facility_id": facility_id,
        "period_grain": period_grain,
        "period_start": period_start,
        "period_end": period_end,
        "files_processed": len(reports),
        "avg_coverage_ratio": sum(coverage) / len(coverage) if coverage else None,
        "total_rows_seen": sum(_number(report, "total_rows") for report in reports),
        "accepted_rows": sum(_number(report, "accepted_rows") for report in reports),
        "flagged_rows": sum(_number(report, "flagged_rows") for report in reports),
        "rejected_rows": sum(_number(report, "rejected_rows") for report in reports),
        "top_issue_codes": top_issues,
    }
