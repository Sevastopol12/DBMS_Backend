"""Small, process-local logging configuration shared by API and workers."""

from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler


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
    root.addHandler(stdout_handler)
    if log_file := os.getenv("LOG_FILE"):
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    root._dbms_logging_configured = True


__all__ = ["configure_logging"]
