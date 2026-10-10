from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID

from backend.api.dto import (
    RejectedArtifactDownload,
    RejectedArtifactItem,
    RejectedArtifactListResponse,
)
from backend.database.service.storage import (
    presigned_get_ttl_from_env,
    rejection_key_for_file,
)
from backend.timezone import ensure_vietnam_aware, now_vietnam

logger = logging.getLogger(__name__)
RejectionState = Literal["available", "expired"]


class RejectionNotFoundError(Exception):
    pass


class RejectionExpiredError(Exception):
    pass


class RejectionUnavailableError(Exception):
    pass


class InvalidCursorError(ValueError):
    pass


class RejectedArtifactRepository(Protocol):
    async def get_rejected_artifact(
        self, *, facility_id: UUID, file_id: UUID
    ) -> Any | None: ...

    async def list_rejected_artifacts(
        self,
        *,
        facility_id: UUID,
        limit: int,
        after: tuple[datetime, str] | None,
        state_filter: str | None,
        now: datetime,
    ) -> list[Any]: ...


class RejectionStorage(Protocol):
    def exists(self, key: str) -> bool: ...

    def presign_get(
        self,
        key: str,
        ttl_seconds: int | None = None,
        download_filename: str | None = None,
    ) -> str: ...


def artifact_state(record: Any, now: datetime | None = None) -> RejectionState:
    current = now or now_vietnam()
    expires = record.artifact_expires_at
    if current.tzinfo is None:
        current = ensure_vietnam_aware(current)
    if expires is not None and expires.tzinfo is None:
        expires = ensure_vietnam_aware(expires)
    if record.artifact_purged_at is not None or expires is None or expires <= current:
        return "expired"
    return "available"


def encode_cursor(created_at: datetime, file_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{file_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        encoded = cursor.encode("ascii")
        raw = base64.b64decode(
            encoded + b"=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        ).decode("utf-8")
        created_raw, file_raw = raw.rsplit("|", 1)
        created_at = datetime.fromisoformat(created_raw)
        file_id = UUID(file_raw)
        if created_at.tzinfo is None:
            created_at = ensure_vietnam_aware(created_at)
        return created_at, str(file_id)
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise InvalidCursorError("invalid cursor") from exc


def _source_filename(record: Any) -> str:
    for attr in ("source_filename", "filename"):
        value = getattr(record, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _display_filename(source_filename: str | None, file_id: UUID) -> str:
    """Download name built from the original upload's name.
    ``{original_stem}_rejected.xlsx``; falls back to
    ``rejected_{file_id}.xlsx`` only when the source name is missing.
    """

    if source_filename:
        from pathlib import PurePath

        base = PurePath(source_filename).name.strip()
        if base and base not in {".", ".."}:
            stem = base.rsplit(".", 1)[0].strip() if "." in base else base
            if stem:
                return f"{stem}_rejected.xlsx"
    return f"rejected_{file_id}.xlsx"


def _item(record: Any, now: datetime) -> RejectedArtifactItem:
    filename = _display_filename(_source_filename(record), record.file_id)
    return RejectedArtifactItem(
        file_id=record.file_id,
        filename=filename,
        parent_file_id=record.parent_file_id,
        file_status=str(record.file_status),
        state=artifact_state(record, now),
        artifact_created_at=record.artifact_created_at,
        artifact_expires_at=record.artifact_expires_at,
        rejected_row_count=record.rejected_row_count,
    )


class RejectionService:
    def __init__(
        self, repository: RejectedArtifactRepository, storage: RejectionStorage
    ):
        self._repository = repository
        self._storage = storage

    @staticmethod
    def _expected_key(facility_id: UUID, file_id: UUID) -> str:
        return rejection_key_for_file(facility_id, file_id)

    async def _record(self, facility_id: UUID, file_id: UUID) -> Any:
        try:
            record = await self._repository.get_rejected_artifact(
                facility_id=facility_id, file_id=file_id
            )
        except Exception as exc:
            logger.warning("rejection artifact lookup failed: %s", type(exc).__name__)
            raise RejectionUnavailableError() from exc
        if record is None or record.artifact_key != self._expected_key(
            facility_id, file_id
        ):
            raise RejectionNotFoundError()
        return record

    async def list_artifacts(
        self,
        *,
        facility_id: UUID,
        limit: int,
        cursor: str | None,
        state: RejectionState | None,
    ) -> RejectedArtifactListResponse:
        after = decode_cursor(cursor)
        now = now_vietnam()
        try:
            records = await self._repository.list_rejected_artifacts(
                facility_id=facility_id,
                limit=limit + 1,
                after=after,
                state_filter=state,
                now=now,
            )
        except Exception as exc:
            logger.warning("rejection artifact list failed: %s", type(exc).__name__)
            raise RejectionUnavailableError() from exc
        records = [
            r
            for r in records
            if r.artifact_key == self._expected_key(facility_id, r.file_id)
        ]
        has_more = len(records) > limit
        page = records[:limit]
        items = [_item(record, now) for record in page]
        next_cursor = None
        if has_more and page:
            tail = page[-1]
            created_at = tail.artifact_created_at or now
            next_cursor = encode_cursor(created_at, tail.file_id)
        return RejectedArtifactListResponse(
            items=items, next_cursor=next_cursor, limit=limit
        )

    async def get_artifact(
        self, *, facility_id: UUID, file_id: UUID
    ) -> RejectedArtifactItem:
        record = await self._record(facility_id, file_id)
        return _item(record, now_vietnam())

    async def download_artifact(
        self, *, facility_id: UUID, file_id: UUID
    ) -> RejectedArtifactDownload:
        record = await self._record(facility_id, file_id)
        now = now_vietnam()
        if artifact_state(record, now) == "expired":
            raise RejectionExpiredError()
        key = record.artifact_key
        try:
            if not await asyncio.to_thread(self._storage.exists, key):
                raise RejectionExpiredError()
            ttl = presigned_get_ttl_from_env()
            filename = _display_filename(_source_filename(record), file_id)
            url = await asyncio.to_thread(self._storage.presign_get, key, ttl, filename)
        except RejectionExpiredError:
            raise
        except Exception as exc:
            logger.warning("rejection artifact storage failed: %s", type(exc).__name__)
            raise RejectionUnavailableError() from exc
        return RejectedArtifactDownload(
            file_id=file_id,
            download_url=url,
            artifact_filename=filename,
            url_expires_at=now + timedelta(seconds=ttl),
        )


__all__ = [
    "InvalidCursorError",
    "RejectionExpiredError",
    "RejectionNotFoundError",
    "RejectionService",
    "RejectionUnavailableError",
    "artifact_state",
    "decode_cursor",
    "encode_cursor",
]
