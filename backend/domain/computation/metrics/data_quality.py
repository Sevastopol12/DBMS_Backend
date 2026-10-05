"""Quality-report aggregates for ingestion files."""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from datetime import datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


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


def _eligible_reports(files: pd.DataFrame) -> list[dict[str, Any]]:
    values = files["quality_report"] if "quality_report" in files else pd.Series(dtype=object)
    reports: list[dict[str, Any]] = []
    skipped = 0
    for value in values.tolist():
        report = _quality_report(value)
        if report and "accepted_clean_rows" in report:
            reports.append(report)
        else:
            skipped += 1
    if skipped:
        logger.info("skipped %d legacy or invalid quality reports", skipped)
    return reports


def quality_eligible_mask(files: pd.DataFrame) -> pd.Series:
    values = files["quality_report"] if "quality_report" in files else pd.Series(dtype=object)
    return values.map(
        lambda value: bool(
            (report := _quality_report(value))
            and "accepted_clean_rows" in report
        )
    )


def compute_data_quality(
    files: pd.DataFrame,
    *,
    facility_id: Any = None,
    period_grain: str | None = None,
    period_start: datetime | pd.Timestamp | None = None,
    period_end: datetime | pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Aggregate only current-schema quality reports in one period slice."""

    reports = _eligible_reports(files)
    coverage: list[float] = []
    issue_counts: Counter[str] = Counter()
    for report in reports:
        try:
            ratio = float(report.get("coverage_ratio"))
            if math.isfinite(ratio):
                coverage.append(ratio)
        except (TypeError, ValueError):
            pass
        raw_issues = report.get("issue_code_counts") or {}
        if isinstance(raw_issues, dict):
            for code, count in raw_issues.items():
                try:
                    issue_counts[str(code)] += int(count)
                except (TypeError, ValueError):
                    continue

    return {
        "facility_id": facility_id,
        "period_grain": period_grain,
        "period_start": period_start,
        "period_end": period_end,
        "files_processed": len(reports),
        "avg_mapping_coverage_ratio": sum(coverage) / len(coverage) if coverage else None,
        "total_rows_seen": sum(_number(report, "total_rows") for report in reports),
        "accepted_clean_rows": sum(_number(report, "accepted_clean_rows") for report in reports),
        "accepted_with_flags_rows": sum(
            _number(report, "accepted_with_flags_rows") for report in reports
        ),
        "rejected_rows": sum(_number(report, "rejected_rows") for report in reports),
        "top_issue_codes": [
            {"code": code, "count": count}
            for code, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
        ],
    }


__all__ = ["compute_data_quality", "quality_eligible_mask"]
