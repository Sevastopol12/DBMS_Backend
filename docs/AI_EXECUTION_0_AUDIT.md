# Repository overview

This repository is an early FastAPI/Celery/PostgreSQL/S3 ingestion skeleton. The tracked source tree contains the API, database adapters, a worker and mapping stub, but no implementation of file reading or transformation and no test files. Audit scope was the complete tracked repository plus the current uncommitted working tree, which is relevant because it currently prevents imports.

Environment/configuration dependencies are `STAGING_RDB_URL`, `APPLICATION_RDB_URL`, `STORAGE_KEY`, `STORAGE_SECRET`, `STORAGE_ENDPOINT`, `STORAGE_REGION`, `STAGING_BUCKET`, `BROKER_URL`, `CACHE_HOST`, `CACHE_PORT`, and `COLUMN_CACHE`. They are read without validation. [MEDIUM] `backend/database/connection/rdb.py:create_connection`, `backend/database/connection/storage.py:get_storage_config`, `backend/celery/config.py`, `backend/redis/__init__.py:get_application_cache`.

No `mapping.json`, `backend/domain/ingestion/` package, migration tooling, compose file, or tests directory exists in the tracked repository. [HIGH] repository-wide.

# Actual ingestion call graph

Intended executable path (currently blocked at import):

```text
POST /upload/v1/ingestions
  main.py -> backend.api.upload:create_upload
  -> IngestionService.get_upload
  -> IngestionRepository.create(FileInfo CREATED) [staging transaction]
  -> StorageService.get_presigned_url (S3 PUT URL)

client uploads directly to S3

POST /upload/v1/{file}/complete
  -> IngestionService.complete_upload
  -> IngestionRepository.get [transaction]
  -> StorageService.get_file_metadata (S3 HEAD)
  -> IngestionRepository.complete_upload (QUEUED) [transaction]
  -> celery task transform.delay(file id)
  -> tasks.transform:_transform
  -> FileProcessor.process_file
  -> IngestionRepository.claim (PROCESSING) [atomic update transaction]
  -> StorageService.get(object_key)
  -> FileProcessor._apply_transform [TODO / returns None]
  -> ReportRepository.bulk_insert(result.rows) [production transaction]
  -> IngestionRepository.update(SUCCEED) [staging transaction]
```

`backend/domain/models/__init__.py` fails first because it imports the absent `ErrorLog`; therefore the app/router and worker cannot import. [BLOCKER] `backend/domain/models/__init__.py:ErrorLog`.

The completion route path declares `{file}` but its handler has no `file` parameter; FastAPI treats that as an unused route path parameter, so the arbitrary path segment is not validated or compared to `request.id`. [MEDIUM] `backend/api/upload.py:complete_upload`.

`transform.delay()` is invoked only after `complete_upload` returns. There is no outbox/transactional dispatch, so a broker failure after the staging update leaves a file QUEUED without a task; a task can also be delivered before the HTTP response. [HIGH] `backend/api/upload.py:complete_upload`, `backend/database/service/repository/staging.py:complete_upload`.

# Transformation call graph

There is no implemented reader, header normalization pipeline, mapper, extractor, normalizer, validator, quality reporter, or error persistence path. The sole transform entry point is `FileProcessor._apply_transform`, which is an async TODO containing only `...`; it returns `None`. [BLOCKER] `backend/domain/processor/__init__.py:_apply_transform`.

The intended consumer assumes `result.rows`, `accepted_row_count`, and `rejected_row_count`. `TransformResult` declares only the counts and file ID, not `rows`; even a future `TransformResult` instance would fail at `result.rows`. [BLOCKER] `backend/domain/processor/__init__.py:process_file`, `backend/domain/models/transform.py:TransformResult`.

`TaskReport` is an unused alternative result shape (`report_rows`, `logs`, counts), and its list-of-dicts rows do not meet `ReportRepository.bulk_insert`'s `Sequence[ReportRow]` contract. [HIGH] `backend/domain/models/transform.py:TaskReport`, `backend/database/service/repository/production.py:bulk_insert`.

# Existing contracts

`IngestionCreate` accepts filename, optional unused `content`, and content type. `IngestionComplete` supplies UUID, hash, optional size, and optional `dict[str, str]` mappings. The repository annotation requires non-optional `dict[str, str]`; `None` is nevertheless passed to the JSONB field. [MEDIUM] `backend/domain/models/api.py:IngestionCreate/IngestionComplete`, `backend/database/service/repository/staging.py:complete_upload`.

`StorageService.get` is declared `-> bytes`, returns botocore's streaming body, and returns `None` for all non-`NoSuchKey` client errors. `FileProcessor` happens to call `.read()`, which agrees with the body object but not the annotation. [HIGH] `backend/database/service/storage.py:get`, `backend/domain/processor/__init__.py:process_file`.

`ReportRepository` imports `ReportRow` from nonexistent `backend.domain.ingestion.contracts`; the actual class is in `backend.domain.models.transform`. This confirmed missing-contract-module issue is masked by the earlier `ErrorLog` import failure. [BLOCKER] `backend/database/service/repository/production.py:ReportRow`.

The current worktree renamed `ErrorLog` to `ColumnErrorLog`, but the public models package still imports/exports `ErrorLog`. No source imports `ColumnErrorLog`; `FileErrorRecord` is likewise never inserted. [BLOCKER] `backend/domain/models/__init__.py`, `backend/domain/models/transform.py:ColumnErrorLog`, `backend/database/schema/__init__.py:FileErrorRecord`.

# Mapping architecture

Mappings enter the ingestion flow from the completion request (`IngestionComplete.mappings`) and are stored as `FileInfo.mappings` JSONB. They are returned by `claim` and passed unchanged to the unimplemented transformer. [MEDIUM] `backend/domain/models/api.py`, `backend/database/service/repository/staging.py:complete_upload/claim`, `backend/domain/processor/__init__.py:_apply_transform`.

Separately, `POST /fetch/v1/mapping/{filename}` ignores the route filename and calls Redis synchronously. For each submitted column, it obtains `HGET COLUMN_CACHE <original-column>`; if missing, it returns a normalized source name as the target. Redis responses are bytes by default, incompatible with `MappingResponse.mapping: dict[str, str | None]`, and neither mappings nor frontend completion mappings are written to Redis. [HIGH] `backend/api/fetch.py:get_mapping`, `backend/redis/__init__.py:RedisCache.get_mapping`.

`backend.redis` imports `normalize_column_name` from nonexistent `backend.domain.ingestion.mapping`. An equivalent current-worktree helper instead exists at `backend.domain.utils.normalize_column_name`, but is not used by Redis. [BLOCKER] `backend/redis/__init__.py`.

There is no `mapping.json`. The untracked `map.py` is inert: no module imports it and it is not loaded into Redis. It defines `DIRECT_ALIASES`, mapping many normalized source aliases to a single `(target, confidence)` tuple, and `STRUCTURAL_RULES`: a blood-pressure composite maps one column to two targets; gender indicators and split-name rules combine multiple columns to one target; DOB derives birth year. The runtime Redis API cannot express confidences, structural rules, one-to-many output, or multi-column input. [HIGH] `map.py:DIRECT_ALIASES/STRUCTURAL_RULES`, `backend/redis/__init__.py`.

# Persistence architecture

Staging `FileInfo` is persisted in PostgreSQL schema `Files`; report records use schema `Diabetes`. There is no code that creates `FileInfo`, `SystemReport`, or `FileErrorRecord` schemas/tables on startup; `IngestionRepository.create_table_and_schema` exists but is unused and only creates the provided table/schema. [HIGH] `backend/database/schema/__init__.py`, `backend/database/service/repository/staging.py:create_table_and_schema`.

`SystemReport` requires `source_file_id` and `row_index`; all domain `ReportRow` fields are nullable. `row_index` does not exist in `ReportRow`, yet `bulk_insert` builds values only from `row.model_fields`, so inserts omit a non-null column. [BLOCKER] `backend/database/schema/__init__.py:SystemReport`, `backend/domain/models/transform.py:ReportRow`, `backend/database/service/repository/production.py:bulk_insert`.

`SystemReport` has unique constraint `source_unique(source_file_id, row_index)` in the current worktree and uses PostgreSQL `ON CONFLICT DO NOTHING`, returning accurate insert/skipped counts within the same database transaction. This is row-level idempotency only if the transform provides stable row indexes. The worker discards that result and records transform counts instead. [HIGH] `backend/database/schema/__init__.py:SystemReport`, `backend/database/service/repository/production.py:bulk_insert`, `backend/domain/processor/__init__.py:process_file`.

There is no staging database unique constraint on `FileInfo.content_hash`. The repository catches an integrity error containing `content_hash`, but no such constraint is defined, so duplicate-content detection is ineffective. [HIGH] `backend/database/schema/__init__.py:FileInfo`, `backend/database/service/repository/staging.py:complete_upload`.

Invalid rows cannot be handled: transformation/validation is absent, `FileErrorRecord` has no repository/service, and no invalid-row decision is implemented. [BLOCKER] `backend/domain/processor/__init__.py:_apply_transform`, `backend/database/schema/__init__.py:FileErrorRecord`.

# State machine

The requested `PENDING` state does not exist. The implemented initial state is `CREATED`, so `PENDING` is disproved. [HIGH] `backend/domain/models/api.py:FileStatus`, `backend/database/service/ingestion.py:get_upload`.

| Transition | Actor and transaction | Retry/idempotency |
| --- | --- | --- |
| absent -> CREATED | `get_upload` -> `IngestionRepository.create`; one staging-session transaction | New UUID each call; no dedupe. |
| CREATED -> QUEUED | completion endpoint -> `complete_upload`; one staging-session update after S3 HEAD | Repeated calls while QUEUED/PROCESSING return unchanged state without checking supplied hash/size/mapping. QUEUED can be reset only indirectly by calling completion after ERROR/SUCCEED. |
| QUEUED -> PROCESSING | Celery task -> `claim`; atomic conditional staging update | Concurrent tasks: only one claims. No Celery retry configuration. |
| PROCESSING -> SUCCEED | worker after production bulk insert -> `update`; separate staging transaction | A crash after insert and before update leaves PROCESSING; re-delivery cannot reclaim it. |
| PROCESSING -> ERROR | worker `_fail`; separate staging update | No automatic retry or recovery/requeue mechanism. |
| completion exception -> ERROR | `IngestionService.complete_upload` exception handler | It marks any error, including duplicate conflict or client size mismatch, as ERROR; an update failure can mask original failure. |

`FileStatus` is typed as `Mapped[str]` while assigned enum values; serialization likely works because it is a `str` enum, but the ORM model is not enum-typed. [LOW] `backend/database/schema/__init__.py:FileInfo.status`.

# Existing tests

No `tests/` directory or test modules exist. [HIGH] repository-wide.

Baseline command: `uv run python -m pytest`.

Result: 0 passed, 0 failed, 0 skipped, 0 collection/import errors; pytest collected 0 items. Warnings: configured `tests` path does not exist, and `asyncio_mode` is unknown because `pytest-asyncio` is not installed. This does not demonstrate that application imports work; direct import probes fail with the blocking `ErrorLog` ImportError.

# Confirmed inconsistencies

| Severity | Files / symbol | Confirmed issue |
| --- | --- | --- |
| BLOCKER | `backend/domain/models/__init__.py:ErrorLog` | Exports a class removed/renamed to `ColumnErrorLog`. |
| BLOCKER | `backend/database/service/repository/production.py:ReportRow` | Imports missing `backend.domain.ingestion.contracts`. |
| BLOCKER | `backend/redis/__init__.py:normalize_column_name` | Imports missing `backend.domain.ingestion.mapping`. |
| BLOCKER | `FileProcessor._apply_transform` / `TransformResult` | Stub returns `None`; consumer requires absent `rows`. |
| BLOCKER | `SystemReport.row_index` / `ReportRow` | Required report column is missing from row model and inserts. |
| HIGH | `StorageService.get` | Annotation says bytes; actual success value is streaming body and some errors return None. |
| HIGH | `FileInfo.content_hash` / staging repository | Duplicate detection assumes an unavailable database uniqueness constraint. |
| HIGH | `map.py` / Redis | Inert Python mapping catalog differs structurally and semantically from the flat Redis hash reader; no mapping JSON exists. |
| HIGH | `backend/celery/config.py` | The transform task name exactly matches its route and is routed to the declared `transform` queue (so that portion is consistent). However, `backend.celery.tasks.populate` is routed to a declared `populate` queue although no such task/module exists, and no retry or delivery policy exists. |
| MEDIUM | `backend/api/fetch.py:get_mapping` | Route `{filename}` is unused; Redis's bytes output violates response model. |
| MEDIUM | `backend/api/upload.py:complete_upload` | Route `{file}` is unused; completion and dispatch are not atomic. |

# Risks

Production ingestion cannot start because package imports fail. If those imports were repaired without completing contracts, every claimed file would become ERROR when the transform result is accessed. [BLOCKER] `backend/domain/models/__init__.py`, `backend/domain/processor/__init__.py`.

The lack of a transactional outbox, task retry, recovery for stuck PROCESSING records, and content-hash uniqueness can cause lost work, permanently stuck work, and duplicate uploads. [HIGH] API, Celery, and staging repository path above.

Direct S3 client calls and synchronous Redis calls run in async request handlers; they may block the event loop. No credentials, endpoints, or database URL validation prevents late runtime failures. [MEDIUM] `backend/database/service/storage.py`, `backend/redis/__init__.py`, configuration modules.

# Recommended minimum contract changes

1. Establish one importable transformation contract: canonical `ReportRow` (including stable `row_index`), `TransformResult(rows, accepted/rejected counts, errors)`, and one canonical error-log name. [BLOCKER] `backend/domain/models/*`, `backend/domain/processor/*`, `backend/database/service/repository/production.py`.
2. Implement the transform boundary with explicit reader input/output contracts before persistence: CSV/XLSX read, normalized headers, mapping, extraction, normalization, validation, result/error collection. [BLOCKER] new transformation modules and `FileProcessor._apply_transform`.
3. Define and enforce the mapping schema shared by frontend completion, Redis suggestion lookup, and any alias/structural-rule catalog; decode Redis responses and decide how composite/multi-source rules are represented. [BLOCKER] API models, Redis cache, mapping catalog.
4. Add a staging unique constraint/index for the intended content-deduplication semantics, then make conflict handling match it. [HIGH] `FileInfo` schema and staging repository.
5. Make S3 return a documented bytes/stream type and handle all client errors consistently. [HIGH] `StorageService.get`, processor.
6. Define durable task-dispatch/retry/recovery behavior and align Celery queue/routing keys with worker deployment configuration. [HIGH] upload flow and Celery config.
7. Add migrations/startup schema strategy and tests for imports, API lifecycle, storage errors, mapping, transformation, report conflict behavior, and state transitions. [HIGH] database and tests.

# Files that should be modified in subsequent executions

`backend/domain/models/__init__.py`, `backend/domain/models/transform.py`, `backend/domain/processor/__init__.py`, `backend/database/service/repository/production.py`, `backend/database/service/repository/staging.py`, `backend/database/schema/__init__.py`, `backend/database/service/storage.py`, `backend/redis/__init__.py`, `backend/api/upload.py`, `backend/api/fetch.py`, `backend/celery/config.py`, `backend/celery/tasks/transform.py`, and new dedicated transformation/mapping/contract modules plus tests and migration/configuration artifacts. [BLOCKER/HIGH]

# Files that should NOT be modified

For the next transformation implementation, do not modify `main.py` unless the public route contract is deliberately changed, and do not treat the untracked `map.py` as a runtime source until a mapping-schema decision is approved. Preserve this audit document as the execution-0 baseline. [LOW] `main.py`, `map.py`, `docs/AI_EXECUTION_0_AUDIT.md`.

Likewise, do not overwrite or revert the pre-existing uncommitted changes in `backend/database/schema/__init__.py`, `backend/domain/models/transform.py`, `backend/domain/utils/__init__.py`, or `map.py`; they predate this audit and need human review. [HIGH] current working tree.
