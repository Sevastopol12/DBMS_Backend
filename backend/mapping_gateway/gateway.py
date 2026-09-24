from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

import redis
from sqlalchemy.engine import make_url

from backend.domain.ingestion.mapping.snapshot import (
    MappingSnapshot,
    MappingSource,
    MappingSourceKind,
    MappingSourceUnavailable,
    UnavailableMappingSource,
)


logger = logging.getLogger(__name__)


class _RedisSkipped(Exception):
    pass


class _RedisFailed(Exception):
    pass


class MappingLookupGateway:
    """Redis-first mapping source with a fail-closed database fallback."""

    def __init__(
        self,
        *,
        redis_client_factory: Callable[[], Any],
        db_loader: Callable[[], Any],
        direct_key: str,
        dynamic_key: str,
        clock: Callable[[], float] = time.monotonic,
        cooldown_seconds: float = 10.0,
        db_timeout_seconds: float = 5.0,
        redis_max_workers: int = 8,
        still_down_log_seconds: float = 60.0,
        redis_host: str | None = None,
        redis_port: str | int | None = None,
        db_target: str = "MAPPING_RDB_URL (unset)",
    ) -> None:
        self._redis_client_factory = redis_client_factory
        self._db_loader = db_loader
        self._direct_key = direct_key
        self._dynamic_key = dynamic_key
        self._clock = clock
        self._cooldown_seconds = cooldown_seconds
        self._db_timeout_seconds = db_timeout_seconds
        self._redis_max_workers = redis_max_workers
        self._still_down_log_seconds = still_down_log_seconds
        self._redis_host = (
            os.getenv("CACHE_HOST") if redis_host is None else str(redis_host)
        )
        self._redis_port = (
            os.getenv("CACHE_PORT") if redis_port is None else str(redis_port)
        )
        self._db_target = db_target

        self._lock = threading.Lock()
        self._redis_client: Any | None = None
        self._redis_executor: ThreadPoolExecutor | None = None
        self.db_snapshot: MappingSnapshot | None = None
        self._inflight: Future[MappingSnapshot] | None = None
        self.redis_degraded = False
        self.redis_probing = False
        self.redis_retry_at = 0.0
        self.db_retry_at = 0.0
        self.last_kind: MappingSourceKind | None = None
        self.last_kind_since: float | None = None
        self.last_state_log_at: float | None = None

    async def acquire(self) -> MappingSource:
        """Return the best currently available mapping source."""

        should_try_redis, owns_probe = self._claim_redis_attempt(self._clock())
        if should_try_redis:
            try:
                try:
                    loop = asyncio.get_running_loop()
                    executor = self._get_redis_executor()
                    snapshot = await loop.run_in_executor(
                        executor, self._redis_attempt, owns_probe
                    )
                    return self._publish_source(snapshot)
                except asyncio.CancelledError:
                    raise
                except (_RedisSkipped, _RedisFailed):
                    pass
            finally:
                if owns_probe:
                    with self._lock:
                        self.redis_probing = False

        now = self._clock()
        with self._lock:
            snapshot = self.db_snapshot
            db_retry_at = self.db_retry_at
            future = self._inflight
            if snapshot is not None:
                leader = False
            elif now < db_retry_at:
                snapshot = UnavailableMappingSource()
                leader = False
            elif future is None:
                future = Future()
                self._inflight = future
                leader = True
            else:
                leader = False

        if snapshot is not None:
            return self._publish_source(snapshot)

        if not leader:
            try:
                snapshot = await asyncio.shield(asyncio.wrap_future(future))
            except MappingSourceUnavailable:
                snapshot = UnavailableMappingSource()
            return self._publish_source(snapshot)

        try:
            rows = await asyncio.wait_for(
                self._db_loader(), timeout=self._db_timeout_seconds
            )
            rows_list = list(rows)
            snapshot = MappingSnapshot.from_rows(rows_list)
            if not snapshot.is_complete:
                raise MappingSourceUnavailable("incomplete mapping database snapshot")

            with self._lock:
                self.db_snapshot = snapshot
                self.db_retry_at = 0.0
                future.set_result(snapshot)
            return self._publish_source(snapshot)
        except asyncio.CancelledError:
            self._fail_db_load(future, asyncio.CancelledError())
            raise
        except BaseException as exc:
            self._fail_db_load(future, exc)
            return self._publish_source(UnavailableMappingSource())
        finally:
            with self._lock:
                if self._inflight is future:
                    self._inflight = None

    def close(self) -> None:
        with self._lock:
            executor = self._redis_executor
            self._redis_executor = None
            self._redis_client = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _claim_redis_attempt(self, now: float) -> tuple[bool, bool]:
        with self._lock:
            if not self.redis_degraded:
                return True, False
            if now < self.redis_retry_at or self.redis_probing:
                return False, False
            self.redis_probing = True
            return True, True

    def _get_redis_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._redis_client is None:
                self._redis_client = self._redis_client_factory()
            if self._redis_executor is None:
                self._redis_executor = ThreadPoolExecutor(
                    max_workers=self._redis_max_workers,
                    thread_name_prefix="mapping-redis",
                )
            return self._redis_executor

    def _redis_attempt(self, is_probe: bool) -> MappingSnapshot:
        try:
            with self._lock:
                if not is_probe and self.redis_degraded:
                    raise _RedisSkipped()
                client = self._redis_client
            if client is None:
                raise RuntimeError("Redis client was not initialized")
            direct_raw = client.hgetall(self._direct_key)
            dynamic_raw = client.hgetall(self._dynamic_key)
            snapshot = MappingSnapshot.from_redis_hashes(direct_raw, dynamic_raw)
            if not snapshot.is_complete:
                raise ValueError("incomplete Redis mapping snapshot")
        except _RedisSkipped:
            raise
        except (
            redis.exceptions.RedisError,
            OSError,
            TimeoutError,
            ValueError,
        ) as exc:
            self._mark_redis_failure(exc)
            raise _RedisFailed() from None
        else:
            self._mark_redis_success()
            return snapshot
        finally:
            if is_probe:
                with self._lock:
                    self.redis_probing = False

    def _mark_redis_success(self) -> None:
        with self._lock:
            self.redis_degraded = False
            self.redis_retry_at = 0.0
            self.db_snapshot = None
            self.db_retry_at = 0.0

    def _mark_redis_failure(self, exc: BaseException) -> None:
        with self._lock:
            first_failure = not self.redis_degraded
            self.redis_degraded = True
            self.redis_retry_at = self._clock() + self._cooldown_seconds
        level = logger.warning if first_failure else logger.debug
        level(
            "Redis unavailable: %s host=%s:%s",
            type(exc).__name__,
            self._redis_host,
            self._redis_port,
        )

    def _fail_db_load(
        self, future: Future[MappingSnapshot], exc: BaseException
    ) -> None:
        unavailable = MappingSourceUnavailable("Mapping database unavailable")
        with self._lock:
            self.db_retry_at = self._clock() + self._cooldown_seconds
            if not future.done():
                future.set_exception(unavailable)
            try:
                future.exception()
            except BaseException:
                pass
        logger.warning(
            "mapping DB snapshot load failed: %s (target: %s)",
            type(exc).__name__,
            self._db_target,
        )

    def _publish_source(self, source: MappingSource) -> MappingSource:
        kind = source.kind
        log_level: int | None = None
        log_message: str | None = None
        with self._lock:
            now = self._clock()
            previous = self.last_kind
            changed = previous is not kind
            if changed:
                previous_since = self.last_kind_since
                self.last_kind = kind
                self.last_kind_since = now
                self.last_state_log_at = now
                if kind is MappingSourceKind.DB and previous is MappingSourceKind.REDIS:
                    log_level = logging.WARNING
                    log_message = "mapping source: DB (Redis unavailable)"
                elif kind is MappingSourceKind.NONE:
                    log_level = logging.ERROR
                    log_message = "mapping source: NONE (Redis and DB unavailable)"
                elif kind is MappingSourceKind.REDIS and previous in {
                    MappingSourceKind.DB,
                    MappingSourceKind.NONE,
                }:
                    elapsed = 0.0 if previous_since is None else now - previous_since
                    log_level = logging.INFO
                    log_message = (
                        f"mapping source: REDIS (recovered after {elapsed:.0f}s)"
                    )
                elif (
                    kind is MappingSourceKind.DB and previous is MappingSourceKind.NONE
                ):
                    log_level = logging.INFO
                    log_message = "mapping source: DB (available)"
            elif kind is not MappingSourceKind.REDIS:
                last_log = self.last_state_log_at
                since = self.last_kind_since
                if (
                    last_log is not None
                    and since is not None
                    and now - last_log >= self._still_down_log_seconds
                ):
                    elapsed = now - since
                    log_level = (
                        logging.ERROR
                        if kind is MappingSourceKind.NONE
                        else logging.WARNING
                    )
                    label = (
                        "NONE (Redis and DB unavailable)"
                        if kind is MappingSourceKind.NONE
                        else "DB (Redis unavailable)"
                    )
                    log_message = f"mapping source: {label}, still, for {elapsed:.0f}s"
                    self.last_state_log_at = now
        if log_level is not None and log_message is not None:
            logger.log(log_level, log_message)
        return source


_gateway_lock = threading.Lock()
_gateway: MappingLookupGateway | None = None


def _default_redis_client_factory() -> Any:
    return redis.Redis(
        host=os.getenv("CACHE_HOST"),
        port=os.getenv("CACHE_PORT"),
        socket_connect_timeout=1.0,
        socket_timeout=2.0,
    )


def _default_db_target() -> str:
    raw_url = os.getenv("MAPPING_RDB_URL")
    if not raw_url:
        return "MAPPING_RDB_URL (unset)"
    try:
        url = make_url(raw_url)
    except Exception:
        return "MAPPING_RDB_URL (unset)"
    host = url.host or ""
    port = f":{url.port}" if url.port is not None else ""
    database = url.database or ""
    return f"MAPPING_RDB_URL host={host}{port} db={database}"


def _build_default_gateway() -> MappingLookupGateway:
    from backend.database import load_header_mappings

    return MappingLookupGateway(
        redis_client_factory=_default_redis_client_factory,
        db_loader=load_header_mappings,
        direct_key=os.getenv("DIRECT_SOURCE", ""),
        dynamic_key=os.getenv("DYNAMIC_SOURCE", ""),
        db_target=_default_db_target(),
    )


def get_mapping_gateway() -> MappingLookupGateway:
    global _gateway
    with _gateway_lock:
        if _gateway is None:
            _gateway = _build_default_gateway()
        return _gateway


def reset_mapping_gateway_for_tests() -> None:
    global _gateway
    with _gateway_lock:
        if _gateway is not None:
            _gateway.close()
        _gateway = None


__all__ = [
    "MappingLookupGateway",
    "get_mapping_gateway",
    "reset_mapping_gateway_for_tests",
]
