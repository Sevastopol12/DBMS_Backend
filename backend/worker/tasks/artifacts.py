from __future__ import annotations

import logging
from asyncio import run
from datetime import datetime

from backend.database.errors import FileObjectNotFound
from backend.database.service import IngestionRepository
from backend.database.service.storage import StorageService
from backend.timezone import now_vietnam

from ..app import celery
from ..resources import task_resources
from ..settings import ArtifactSettings

logger = logging.getLogger(__name__)


@celery.task(name="backend.worker.tasks.artifacts.purge_expired_artifacts")
def purge_expired_artifacts(limit: int | None = None) -> dict[str, int]:
    run(_purge_expired_artifacts(limit=limit))


async def _purge_expired_artifacts(*, limit: int | None = None) -> dict[str, int]:
    async with task_resources() as resources:
        return await purge_expired_storage(
            IngestionRepository(resources.staging),
            StorageService(resources.storage),
            now=now_vietnam(),
            limit=limit
            if limit is not None
            else ArtifactSettings.from_env().purge_limit,
        )


async def purge_expired_storage(
    repository: IngestionRepository,
    storage: StorageService,
    *,
    now: datetime,
    limit: int,
) -> dict[str, int]:
    """Delete expired artifact objects and stamp their purged_at.

    The artifact key/expires columns are retained for audit; purged rows are
    excluded from future sweeps via ``artifact_purged_at IS NULL``. A missing
    object (already deleted out-of-band) is tolerated: purged_at is still
    stamped. Only counts are logged — never keys or row values.
    """

    expired = await repository.list_expired_artifacts(now, limit)
    deleted = 0
    missing = 0
    for row in expired:
        try:
            await storage.delete_object(row.rejection_artifact_key)
            deleted += 1
        except FileObjectNotFound:
            missing += 1
        await repository.mark_artifact_purged(row.id, now)
    logger.info(
        "purged expired rejection artifacts: expired=%d deleted=%d missing=%d",
        len(expired),
        deleted,
        missing,
    )
    return {"expired": len(expired), "deleted": deleted, "missing": missing}


__all__ = ["purge_expired_artifacts", "purge_expired_storage"]
