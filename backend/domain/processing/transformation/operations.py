from __future__ import annotations

import re
from typing import Any

from ..models import FieldPlan, MappingOperation
from .normalization import (
    normalize_header,
    normalize_identifier,
    normalize_text,
    normalized_token,
)


def _values(plan: FieldPlan, row: dict[str, Any]) -> list[Any]:
    return [row.get(column) for column in plan.source_columns]


def _first_usable(values: list[Any]) -> Any:
    for value in values:
        if normalize_text(value) is not None:
            return value
    return None


def concat(plan: FieldPlan, row: dict[str, Any]) -> str | None:
    separator = str(plan.metadata.get("separator", " "))
    parts = [normalize_text(value) for value in _values(plan, row)]
    usable = [part for part in parts if part is not None]
    return separator.join(usable) if usable else None


def split_blood_pressure(plan: FieldPlan, row: dict[str, Any]) -> str | None:
    value = _first_usable(_values(plan, row))
    if value is None:
        return None
    text = normalize_text(value)
    match = re.fullmatch(
        r"\s*([+-]?\d+(?:[.,]\d+)?)\s*[/|xX-]\s*([+-]?\d+(?:[.,]\d+)?)\s*", text or ""
    )
    if not match:
        raise ValueError("blood pressure must contain two slash-separated values")
    role = plan.metadata.get("component") or plan.metadata.get("target_component")
    if (
        role in {"systolic", "huyet_ap_tam_thu"}
        or plan.target_field == "huyet_ap_tam_thu"
    ):
        return match.group(1).replace(",", ".")
    if (
        role in {"diastolic", "huyet_ap_tam_truong"}
        or plan.target_field == "huyet_ap_tam_truong"
    ):
        return match.group(2).replace(",", ".")
    return f"{match.group(1)}/{match.group(2)}"


def _icd_tokens(value: Any) -> list[str]:
    text = normalize_text(value)
    if text is None:
        return []
    return [token for token in re.split(r"[,;|/\s]+", text.upper()) if token]


def classify_icd(value: Any) -> dict[str, str | None]:
    """Classify only the ICD families represented by the canonical schema."""
    hypertension: list[str] = []
    diabetes: list[str] = []
    additional: list[str] = []
    for token in _icd_tokens(value):
        if re.match(r"^I1[0-5](?:\.|$)", token):
            hypertension.append(token)
        elif re.match(r"^E1[0-4](?:\.|$)", token):
            diabetes.append(token)
        else:
            additional.append(token)
    return {
        "icd_tha": ", ".join(hypertension) or None,
        "icd_dtd": ", ".join(diabetes) or None,
        "chan_doan_di_kem": ", ".join(additional) or None,
    }


def split_icd(plan: FieldPlan, row: dict[str, Any]) -> str | None:
    values = [
        value for value in _values(plan, row) if normalize_text(value) is not None
    ]
    if not values:
        return None
    return classify_icd(";".join(str(value) for value in values)).get(
        plan.target_field
    )


def derive_gender(plan: FieldPlan, row: dict[str, Any]) -> str | None:
    female = "\u004e\u1eef"
    active: list[str] = []
    observed = False
    for column, value in zip(plan.source_columns, _values(plan, row)):
        text = normalize_text(value)
        if text is None:
            continue
        token = normalized_token(text) or ""
        normalized_column = normalize_header(column)
        is_nam_column = normalized_column in {
            "nam",
            "male",
            "m",
        } or normalized_column.endswith(("_nam", "_male", "_m"))
        is_nu_column = normalized_column in {
            "nu",
            "female",
            "f",
        } or normalized_column.endswith(("_nu", "_female", "_f"))
        if is_nam_column or is_nu_column:
            observed = True
            if token in {"1", "true", "yes", "nam", "male", "m"}:
                active.append("Nam" if is_nam_column else female)
            elif token in {"0", "false", "no", "nu", "female", "f"}:
                # In a single encoded gender field, Nam=1 and Nam=0 means
                # female. In paired flags, zero means inactive.
                if len(plan.source_columns) == 1:
                    active.append(female if is_nam_column else "Nam")
            else:
                raise ValueError("unrecognized gender flag")
        elif token in {"nam", "male", "m"}:
            observed = True
            active.append("Nam")
        elif token in {"nu", "female", "f"}:
            observed = True
            active.append(female)
        else:
            raise ValueError("unrecognized gender value")
    if not observed:
        return None
    if len(set(active)) > 1:
        raise ValueError("conflicting gender flags")
    if not active:
        return None
    return "Nam" if active[0] == "Nam" else female


def execute_operation(plan: FieldPlan, row: dict[str, Any]) -> Any:
    values = _values(plan, row)
    operation = plan.operation
    if operation is MappingOperation.DIRECT:
        return values[0] if values else None
    if operation is MappingOperation.COALESCE:
        return _first_usable(values)
    if operation is MappingOperation.CONCAT:
        return concat(plan, row)
    if operation is MappingOperation.SPLIT:
        value = _first_usable(values)
        if value is None:
            return None
        delimiter = str(plan.metadata.get("delimiter", ","))
        index = int(plan.metadata.get("index", 0))
        parts = str(value).split(delimiter)
        if index >= len(parts):
            raise ValueError("split index is out of range")
        return parts[index].strip() or None
    if operation is MappingOperation.SPLIT_BLOOD_PRESSURE:
        return split_blood_pressure(plan, row)
    if operation is MappingOperation.SPLIT_ICD:
        return split_icd(plan, row)
    if operation in {
        MappingOperation.DERIVE_GENDER,
        MappingOperation.DERIVE_GENDER_FROM_FLAGS,
    }:
        return derive_gender(plan, row)
    if operation is MappingOperation.PARSE_IDENTIFIER:
        return normalize_identifier(values[0] if values else None)
    return values[0] if values else None


__all__ = [
    "classify_icd",
    "derive_gender",
    "execute_operation",
    "split_blood_pressure",
    "split_icd",
]
