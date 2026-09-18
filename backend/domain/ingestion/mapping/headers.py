from rapidfuzz.fuzz import ratio
from rapidfuzz.process import extractOne

from backend.domain.models import ColumnMap
from backend.redis import RedisCache


EXPLICIT_MAPPING_THRESHOLD = 70.0
FUZZY_MAPPING_THRESHOLD = 80.0


def _clean_mapping_target(value: object) -> str | None:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _cached_mapping(cache_client: RedisCache, source_column: str) -> str | None:
    return _clean_mapping_target(cache_client.get_cached_mapping(source_column))


def _mapping_keys(cache_client: RedisCache) -> list[str]:
    """Return sorted, unique, non-empty keys for deterministic matching."""
    keys = {
        key.strip()
        for key in cache_client.iter_mapping_keys()
        if isinstance(key, str) and key.strip()
    }
    return sorted(keys, key=lambda key: (key, key))


def map_headers(
    cache_client: RedisCache, headers: list[ColumnMap]
) -> tuple[list[ColumnMap], list[ColumnMap]]:

    qualified: list[ColumnMap] = []
    ambiguous: list[ColumnMap] = []

    for header in headers:
        if header.mapping_target is not None:
            if confidence(header.normalized_name, header.mapping_target):
                qualified.append(header)
            else:
                qualified.append(header.model_copy(update={"mapping_target": None}))

        else:
            mapping_target = match_attempt(cache_client, header)
            if mapping_target:
                qualified.append(
                    header.model_copy(update={"mapping_target": mapping_target})
                )
            else:
                ambiguous.append(header)

    return qualified, ambiguous


def match_attempt(cache_client: RedisCache, header: ColumnMap | str) -> str | None:
    source_name = header.normalized_name if isinstance(header, ColumnMap) else header
    print(f"attempt: {source_name}")
    if not isinstance(source_name, str) or not source_name.strip():
        return None

    mapping_target = _cached_mapping(cache_client, source_name)
    if mapping_target is not None:
        return mapping_target

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
        scorer=ratio,
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
    return ratio(header, header) >= threshold
