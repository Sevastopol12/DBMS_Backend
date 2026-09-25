from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

from rapidfuzz.fuzz import partial_ratio

from ...models import ColumnMap
from ...transformation.normalization import normalize_header

if TYPE_CHECKING:
    from ..source.snapshot import MappingSource

from .catalog import MappingCatalog, MatchAttempt, ResolvedHeader


FUZZY_MAPPING_THRESHOLD = 88.0


def _clean_mapping_target(value: object) -> str | None:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _source_column(header: ColumnMap | str) -> ColumnMap:
    if isinstance(header, ColumnMap):
        return header
    return ColumnMap(
        original_name=header,
        normalized_name=normalize_header(header),
        mapping_target=None,
    )


def _cached_result(
    cache_client: MappingSource | None, normalized_name: str
) -> tuple[str, str] | None:
    if cache_client is None:
        return None
    result = cache_client.get_column_cache(normalized_name)
    target = _clean_mapping_target(result.value) if result is not None else None
    if target is None:
        return None
    source = getattr(result.cache_key, "value", result.cache_key)
    return target, str(source).lower()


def _cached_mapping(
    cache_client: MappingSource | None, normalized_name: str
) -> str | None:
    result = _cached_result(cache_client, normalized_name)
    return result[0] if result is not None else None


def _mapping_keys(cache_client: MappingSource | None) -> list[str]:
    if cache_client is None:
        return []
    return sorted(
        {
            key.strip()
            for key in cache_client.iter_mapping_keys()
            if isinstance(key, str) and key.strip()
        }
    )


@dataclass(frozen=True)
class _FuzzyCandidate:
    key: str
    normalized_key: str
    target: str
    score: float
    cache_source: str


def _fuzzy_candidates(
    cache_client: MappingSource | None,
    source_name: str,
    *,
    threshold: float = FUZZY_MAPPING_THRESHOLD,
) -> list[_FuzzyCandidate]:
    candidates: list[_FuzzyCandidate] = []
    for key in _mapping_keys(cache_client):
        normalized_key = normalize_header(key)
        if not normalized_key:
            continue
        score = partial_ratio(source_name, normalized_key)
        if score < threshold:
            continue
        cached = _cached_result(cache_client, normalized_key)
        if cached is None:
            continue
        candidates.append(
            _FuzzyCandidate(
                key=key,
                normalized_key=normalized_key,
                target=cached[0],
                score=score,
                cache_source=cached[1],
            )
        )
    return sorted(
        candidates, key=lambda item: (-item.score, item.normalized_key, item.key)
    )


def _choose_fuzzy_candidate(
    candidates: list[_FuzzyCandidate],
) -> tuple[_FuzzyCandidate | None, bool]:
    """Choose a fuzzy cache candidate without resolving a real tie arbitrarily."""
    if not candidates:
        return None, False
    best_score = candidates[0].score
    best = [candidate for candidate in candidates if candidate.score == best_score]
    targets = {normalize_header(candidate.target) for candidate in best}
    if len(targets) > 1:
        return None, True
    return best[0], False


def _explicit_for(
    column: ColumnMap, explicit_map: dict[str, object] | None
) -> object | None:
    if explicit_map:
        if column.original_name in explicit_map:
            return explicit_map[column.original_name]
        if column.normalized_name in explicit_map:
            return explicit_map[column.normalized_name]
    return column.mapping_target


def match_attempt(
    cache_client: MappingSource | None,
    header: ColumnMap | str,
    explicit_map: dict[str, object] | None = None,
    *,
    samples: Iterable[Any] = (),
    catalog: MappingCatalog,
    return_result: bool = False,
) -> str | MatchAttempt | None:
    """Resolve one header through the authoritative mapping path.

    Precedence is explicit mapping, exact DIRECT/DYNAMIC cache mapping, then
    the historical ``partial_ratio`` fuzzy cache lookup. Fuzzy ties that point
    at different targets remain ambiguous. ``return_result`` retains operation
    metadata for the batch adapter while the default preserves the historical
    target-string contract.
    """
    del samples
    column = _source_column(header)
    source_name = normalize_header(column.original_name)
    catalog = catalog

    explicit = _explicit_for(column, explicit_map)
    if explicit is not None:
        entry = catalog.entry_for_explicit(column, explicit)
        if entry is not None:
            attempt = MatchAttempt(column, entry, 100.0, "explicit")
            return attempt if return_result else _first_target(entry)

    if not source_name:
        attempt = MatchAttempt(column, None, 0.0, "unmapped")
        return attempt if return_result else None

    cached = _cached_result(cache_client, source_name)
    if cached is not None:
        entry = catalog.entry_for_target(column, cached[0], tier=cached[1])
        attempt = MatchAttempt(column, entry, 100.0, f"{cached[1]}_exact")
        return attempt if return_result else cached[0]

    candidate, ambiguous = _choose_fuzzy_candidate(
        _fuzzy_candidates(cache_client, source_name)
    )
    if ambiguous:
        attempt = MatchAttempt(column, None, 0.0, "ambiguous")
        return attempt if return_result else None
    if candidate is None:
        attempt = MatchAttempt(column, None, 0.0, "unmapped")
        return attempt if return_result else None

    entry = catalog.entry_for_target(
        column, candidate.target, tier=candidate.cache_source
    )
    attempt = MatchAttempt(column, entry, candidate.score, "fuzzy")
    return attempt if return_result else candidate.target


def match_headers(
    cache_client: MappingSource | None,
    headers: list[ColumnMap],
    explicit_map: dict[str, object] | None = None,
    *,
    rows: list[dict[str, object]] | None = None,
    catalog: MappingCatalog,
) -> tuple[list[ResolvedHeader], list[ColumnMap], list[ColumnMap]]:
    """Batch adapter around ``match_attempt`` for the ingestion engine."""
    catalog = catalog
    resolved: list[ResolvedHeader] = []
    ambiguous: list[ColumnMap] = []
    unmapped: list[ColumnMap] = []
    rows = rows or []
    for header in headers:
        samples = [row.get(header.original_name) for row in rows[:25]]
        result = match_attempt(
            cache_client,
            header,
            explicit_map,
            samples=samples,
            catalog=catalog,
            return_result=True,
        )
        if not isinstance(result, MatchAttempt) or result.entry is None:
            target = (
                ambiguous
                if isinstance(result, MatchAttempt) and result.resolution == "ambiguous"
                else unmapped
            )
            target.append(header)
            continue
        resolved.append(
            ResolvedHeader(result.source, result.entry, result.score, result.resolution)
        )
    return resolved, ambiguous, unmapped


def _first_target(entry: Any) -> str | None:
    if entry is None or not entry.output_targets:
        return None
    return entry.output_targets[0]


__all__ = [
    "FUZZY_MAPPING_THRESHOLD",
    "match_attempt",
    "match_headers",
]
