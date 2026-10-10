from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float_env(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _str_env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class SweepSettings:
    max_attempts: int = 3
    queued_grace: timedelta = timedelta(seconds=600)
    processing_timeout: timedelta = timedelta(seconds=900)
    retention_days: int = 90
    sweep_interval_seconds: float = 28800.0
    compute_interval_seconds: float = 1800.0

    @classmethod
    def from_env(cls) -> SweepSettings:
        return cls(
            max_attempts=_int_env("TRANSFORM_MAX_ATTEMPTS", 3),
            queued_grace=timedelta(
                seconds=_float_env("TRANSFORM_QUEUED_GRACE_SECONDS", 600.0)
            ),
            processing_timeout=timedelta(
                seconds=_float_env("TRANSFORM_PROCESSING_TIMEOUT_SECONDS", 900.0)
            ),
            retention_days=_int_env("WORKFLOW_LOG_RETENTION_DAYS", 90),
            sweep_interval_seconds=_float_env(
                "TRANSFORM_SWEEP_INTERVAL_SECONDS", 28800.0
            ),
            compute_interval_seconds=_float_env("COMPUTE_INTERVAL_SECONDS", 1800.0),
        )


@dataclass(frozen=True)
class ArtifactSettings:
    """Rejection artifact lifecycle knobs"""

    prefix: str = "REJECTED_FILES"
    retention_days: int = 4
    presigned_ttl_seconds: int = 300
    purge_interval_seconds: float = 86400.0
    purge_limit: int = 1000

    @classmethod
    def from_env(cls) -> ArtifactSettings:
        return cls(
            prefix=_str_env("REJECTED_FILES_PREFIX", "REJECTED_FILES").strip("/")
            or "REJECTED_FILES",
            retention_days=_int_env("REJECTED_ARTIFACT_RETENTION_DAYS", 4),
            presigned_ttl_seconds=_int_env("PRESIGNED_GET_TTL_SECONDS", 300),
            purge_interval_seconds=_float_env(
                "ARTIFACT_PURGE_INTERVAL_SECONDS", 86400.0
            ),
            purge_limit=_int_env("ARTIFACT_PURGE_LIMIT", 1000),
        )


__all__ = ["ArtifactSettings", "SweepSettings"]
