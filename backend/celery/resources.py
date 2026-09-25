from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from backend.database.connection import (
    RDBAsyncConnectionConfig,
    StorageAsyncConnectionConfig,
    close_storage,
    create_connection,
    dispose_connection,
    get_storage_config,
    probe_connection,
    probe_storage,
    storage_settings_from_env,
    task_pool_settings,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskResources:
    staging: RDBAsyncConnectionConfig
    production: RDBAsyncConnectionConfig
    storage: StorageAsyncConnectionConfig


_storage_lock = threading.Lock()
_worker_storage: StorageAsyncConnectionConfig | None = None


def get_worker_storage() -> StorageAsyncConnectionConfig:
    """Return the one thread-safe S3 client shared by worker tasks."""

    global _worker_storage
    with _storage_lock:
        if _worker_storage is None:
            _worker_storage = get_storage_config(**storage_settings_from_env())
        return _worker_storage


def close_worker_storage() -> None:
    """Close and forget the process-wide worker S3 client."""

    global _worker_storage
    with _storage_lock:
        config = _worker_storage
        _worker_storage = None
        if config is not None:
            try:
                close_storage(config)
            except Exception as exc:  # pragma: no cover - defensive shutdown path
                logger.error("worker storage close failed: %s", type(exc).__name__)


def reset_worker_storage_for_tests() -> None:
    """Clear the lazy singleton between isolated tests."""

    close_worker_storage()


async def _dispose_safely(config: RDBAsyncConnectionConfig | None, label: str) -> None:
    if config is None:
        return
    try:
        await dispose_connection(config)
    except Exception as exc:
        logger.error("worker %s engine dispose failed: %s", label, type(exc).__name__)


def _close_storage_safely(config: StorageAsyncConnectionConfig | None) -> None:
    if config is None:
        return
    try:
        close_storage(config)
    except Exception as exc:
        logger.error("worker probe storage close failed: %s", type(exc).__name__)


@asynccontextmanager
async def task_resources() -> AsyncIterator[TaskResources]:
    """Create task-local database engines and dispose them on the same loop."""

    pool = task_pool_settings()
    staging: RDBAsyncConnectionConfig | None = None
    production: RDBAsyncConnectionConfig | None = None
    try:
        staging = create_connection("staging", pool=pool, app_name="dbms-worker")
        production = create_connection("application", pool=pool, app_name="dbms-worker")
        yield TaskResources(
            staging=staging,
            production=production,
            storage=get_worker_storage(),
        )
    finally:
        await _dispose_safely(staging, "staging")
        await _dispose_safely(production, "application")


async def probe_worker_dependencies() -> None:
    """Probe worker dependencies using resources that are never retained."""

    pool = task_pool_settings()
    staging: RDBAsyncConnectionConfig | None = None
    production: RDBAsyncConnectionConfig | None = None
    storage: StorageAsyncConnectionConfig | None = None
    try:
        staging = create_connection("staging", pool=pool, app_name="dbms-worker")
        production = create_connection("application", pool=pool, app_name="dbms-worker")
        storage = get_storage_config(**storage_settings_from_env())

        await probe_connection(staging)
        await probe_connection(production)
        await probe_storage(storage)
    finally:
        await _dispose_safely(staging, "probe staging")
        await _dispose_safely(production, "probe application")
        _close_storage_safely(storage)


__all__ = [
    "TaskResources",
    "close_worker_storage",
    "get_worker_storage",
    "probe_worker_dependencies",
    "reset_worker_storage_for_tests",
    "task_resources",
]
