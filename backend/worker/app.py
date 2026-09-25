import asyncio
import logging
import os

from celery import Celery
from celery.signals import worker_init, worker_shutdown
from sqlalchemy.engine import make_url

from .resources import close_worker_storage, probe_worker_dependencies


logger = logging.getLogger(__name__)

celery = Celery("celery")

celery.config_from_object("backend.worker.config")


def _database_target(env_name: str) -> str:
    raw_url = os.getenv(env_name)
    if not raw_url:
        return f"{env_name} host=(unset) db=(unset)"
    try:
        parsed = make_url(raw_url)
    except Exception:
        return f"{env_name} host=(invalid) db=(invalid)"
    host = parsed.host or "(unset)"
    port = f" port={parsed.port}" if parsed.port is not None else ""
    database = parsed.database or "(unset)"
    return f"{env_name} host={host}{port} db={database}"


@worker_init.connect
def _probe_worker_on_init(sender=None, **kwargs):
    try:
        asyncio.run(probe_worker_dependencies())
    except Exception as exc:
        logger.critical(
            "Celery worker dependency probe failed; stopping worker (%s, %s; %s)",
            _database_target("STAGING_RDB_URL"),
            _database_target("APPLICATION_RDB_URL"),
            type(exc).__name__,
        )
        # Celery's signal dispatcher catches ordinary Exception instances.
        # SystemExit is intentional so a failed boot cannot continue.
        raise SystemExit(1) from None


@worker_shutdown.connect
def _close_worker_on_shutdown(sender=None, **kwargs):
    close_worker_storage()

if __name__ == "__main__":
    celery.start()
