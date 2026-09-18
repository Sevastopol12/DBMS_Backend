from rapidfuzz.fuzz import partial_ratio
from rapidfuzz.process import extractOne

from backend.domain.models import ColumnMap
from backend.domain.ingestion.normalization import normalize_header
from backend.redis import RedisCache


EXPLICIT_MAPPING_THRESHOLD = 78.0
FUZZY_MAPPING_THRESHOLD = 88.0


def _clean_mapping_target(value: object) -> str | None:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _cached_mapping(cache_client: RedisCache, normalized_name: str) -> str | None:
    result = cache_client.get_column_cache(normalized_name)
    if result is None:
        return None
    return _clean_mapping_target(result.value)


def _mapping_keys(cache_client: RedisCache) -> list[str]:
    """Return sorted, unique, non-empty keys for deterministic matching."""
    keys = {
        key.strip()
        for key in cache_client.iter_mapping_keys()
        if isinstance(key, str) and key.strip()
    }
    return sorted(keys)


def map_headers(
    cache_client: RedisCache,
    headers: list[ColumnMap],
    explicit_map: dict[str, str] | None = None,
) -> tuple[list[ColumnMap], list[ColumnMap]]:
    """Map each header through the 4-step pipeline.

    Returns ``(qualified, ambiguous)`` where *qualified* contains headers that
    resolved to a mapping target and *ambiguous* contains those that did not.
    """
    qualified: list[ColumnMap] = []
    ambiguous: list[ColumnMap] = []

    for header in headers:
        mapping_target = match_attempt(cache_client, header, explicit_map)
        if mapping_target:
            qualified.append(
                header.model_copy(update={"mapping_target": mapping_target})
            )
        else:
            ambiguous.append(header)

    return qualified, ambiguous


def match_attempt(
    cache_client: RedisCache,
    header: ColumnMap | str,
    explicit_map: dict[str, str] | None = None,
) -> str | None:
    """Attempt to resolve *header* via the 4-step mapping pipeline.

    Steps (in order):
    1. Explicit mapping (caller-supplied dict) — checked with ``confidence()``.
    2. Redis DIRECT cache lookup by ``normalized_name``.
    3. Redis DYNAMIC cache lookup by ``normalized_name``.
    4. Fuzzy match against all known cache keys -> cache lookup of matched key.

    Returns the resolved mapping target string, or ``None`` if all steps fail.
    """
    source_name = header.normalized_name if isinstance(header, ColumnMap) else header
    if not isinstance(source_name, str) or not source_name.strip():
        return None

    # Explicit mapping (if supplied)
    if explicit_map:
        candidate = explicit_map.get(source_name)
        if candidate and confidence(source_name, candidate):
            return candidate
        # Below threshold — fall through silently to the pipeline

    # Direct cache then dynamic cache
    mapping_target = _cached_mapping(cache_client, source_name)
    if mapping_target is not None:
        return mapping_target

    # Fuzzy match -> cache lookup of the best matching key
    matched_key = fuzzy_match(cache_client, source_name)
    if matched_key is None:
        return None

    return _cached_mapping(cache_client, matched_key)


def fuzzy_match(
    cache_client: RedisCache,
    target_string: str,
    threshold: float = FUZZY_MAPPING_THRESHOLD,
) -> str | None:
    if not isinstance(target_string, str) or not target_string.strip():
        return None

    all_keys = _mapping_keys(cache_client)
    if not all_keys:
        return None

    match = extractOne(
        target_string,
        all_keys,
        scorer=partial_ratio,
        score_cutoff=threshold,
    )
    return match[0] if match is not None else None


def confidence(
    header: str,
    mapping_target: str | None,
    threshold: float = EXPLICIT_MAPPING_THRESHOLD,
) -> bool:
    if not mapping_target:
        return False
    return partial_ratio(header, normalize_header(mapping_target)) >= threshold
