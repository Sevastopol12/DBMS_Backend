"""Small, process-local logging configuration shared by API and workers."""

from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler


class _RedactingFilter(logging.Filter):
    """Redact credentials/secrets from log records (WP-10, edge A12).

    - ``postgresql://...`` / ``postgresql+asyncpg://...`` / ``redis://`` /
      ``rediss://`` URLs -> ``scheme://host[:port]/db`` (no user, password,
      or query string).
    - ``Bearer <token>`` -> ``Bearer [REDACTED]``.
    - ``password=...`` / ``password: ...`` assignments -> ``password=[REDACTED]``.
    """

    _URL_RE = r"(postgresql(?:\+asyncpg)?|postgres|redis|rediss)://[^\s\"']+"
    _BEARER_RE = r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/=]+"
    _PASSWORD_RE = r"(?i)(password\s*[:=]\s*)([^\s,;\"']+)"

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - redaction must never break logging
            return True
        redacted = _redact_text(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def _redact_url(raw: str) -> str:
    import re
    from urllib.parse import urlsplit

    try:
        # Strip asyncpg/SQLAlchemy dialect prefix for parsing.
        normalized = raw
        if normalized.startswith("postgresql+asyncpg://"):
            normalized = "postgresql://" + normalized.removeprefix(
                "postgresql+asyncpg://"
            )
        elif normalized.startswith("postgres://"):
            normalized = "postgresql://" + normalized.removeprefix("postgres://")
        parts = urlsplit(normalized)
        scheme = normalized.split("://", 1)[0]
        host = parts.hostname or "(unknown)"
        port = f":{parts.port}" if parts.port else ""
        db = (parts.path or "").split("?", 1)[0].lstrip("/")
        suffix = f"/{db}" if db else ""
        return f"{scheme}://{host}{port}{suffix}"
    except Exception:  # noqa: BLE001 - fall back to a fully masked URL
        return re.sub(r"://.*", "://[REDACTED]", raw, count=1)


def _redact_text(message: str) -> str:
    import re

    redacted = re.sub(
        _RedactingFilter._URL_RE, lambda m: _redact_url(m.group(0)), message
    )
    redacted = re.sub(_RedactingFilter._BEARER_RE, "Bearer [REDACTED]", redacted)
    redacted = re.sub(_RedactingFilter._PASSWORD_RE, r"\1[REDACTED]", redacted)
    return redacted


class _JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
                "level": record.levelname,
                "service": self.service,
                "logger": record.name,
                "message": record.getMessage(),
            },
            ensure_ascii=False,
        )


def configure_logging(service: str) -> None:
    root = logging.getLogger()
    if getattr(root, "_dbms_logging_configured", False):
        return
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level_name, logging.INFO))
    label = os.getenv("SERVICE_NAME", service)
    if os.getenv("LOG_FORMAT", "text").lower() == "json":
        formatter: logging.Formatter = _JsonFormatter(label)
    else:
        formatter = logging.Formatter(
            f"%(asctime)s %(levelname)s [{label}] %(name)s: %(message)s"
        )
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.addFilter(_RedactingFilter())
    root.addHandler(stdout_handler)
    if log_file := os.getenv("LOG_FILE"):
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(_RedactingFilter())
        root.addHandler(file_handler)
    root._dbms_logging_configured = True


__all__ = ["_RedactingFilter", "configure_logging"]
