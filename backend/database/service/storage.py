from __future__ import annotations

import os
from asyncio import to_thread
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from backend.database.connection import StorageAsyncConnectionConfig
from backend.database.errors import FileObjectNotFound, StorageUnavailable

DEFAULT_REJECTED_FILES_PREFIX = "REJECTED_FILES"
DEFAULT_ARTIFACT_RETENTION_DAYS = 4
DEFAULT_PRESIGNED_GET_TTL_SECONDS = 300


def rejection_prefix_from_env() -> str:
    """Object-storage folder for rejection artifacts."""

    return os.getenv("REJECTED_FILES_PREFIX", DEFAULT_REJECTED_FILES_PREFIX)


def artifact_retention_days_from_env() -> int:
    return int(
        os.getenv(
            "REJECTED_ARTIFACT_RETENTION_DAYS", str(DEFAULT_ARTIFACT_RETENTION_DAYS)
        )
    )


def presigned_get_ttl_from_env() -> int:
    return int(
        os.getenv("PRESIGNED_GET_TTL_SECONDS", str(DEFAULT_PRESIGNED_GET_TTL_SECONDS))
    )


def rejection_key_for_file(
    facility_id: UUID | str, file_id: UUID | str, *, prefix: str | None = None
) -> str:
    """Deterministic artifact key ``<prefix>/<facility_id>/<file_id>.xlsx``.

    Deterministic keys make artifact writes retry-safe: a retried file
    overwrites the same object instead of orphaning a new one.
    """

    clean = (prefix if prefix is not None else rejection_prefix_from_env()).strip("/")
    if not clean:
        clean = DEFAULT_REJECTED_FILES_PREFIX
    return f"{clean}/{facility_id}/{file_id}.xlsx"


def artifact_expires_at(
    base: datetime, *, retention_days: int | None = None
) -> datetime:
    """Expiry instant for an artifact written at ``base``."""

    days = (
        retention_days
        if retention_days is not None
        else artifact_retention_days_from_env()
    )
    return base + timedelta(days=days)


class StorageService:
    def __init__(self, config: StorageAsyncConnectionConfig):
        self.connection_config = config

    def get_presigned_url(self, object_key: str, content_type: str) -> str:
        return self.connection_config.client.generate_presigned_url(
            ClientMethod="put_object",
            ExpiresIn=60,
            Params={
                "Bucket": self.connection_config.bucket,
                "Key": object_key,
                "ContentType": content_type,
            },
            HttpMethod="PUT",
        )

    async def get_file_metadata(self, obj_key: str) -> dict[str, Any]:
        return await to_thread(
            self.connection_config.client.head_object,
            Bucket=self.connection_config.bucket,
            Key=obj_key,
        )

    def get(self, obj_key: str) -> bytes | None:
        try:
            response = self.connection_config.client.get_object(
                Bucket=self.connection_config.bucket, Key=obj_key
            )

            if response["ContentLength"] == 0:
                return None

            return response["Body"].read()

        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code == "NoSuchKey":
                raise FileObjectNotFound()
            raise StorageUnavailable() from exc

    async def put_object(self, key: str, data: bytes, content_type: str) -> None:
        """Upload artifact bytes, overwriting any previous object at ``key``."""

        try:
            await to_thread(
                self.connection_config.client.put_object,
                Bucket=self.connection_config.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except (ClientError, BotoCoreError, NoCredentialsError) as exc:
            raise StorageUnavailable() from exc

    def presign_get(
        self,
        key: str,
        ttl_seconds: int | None = None,
        download_filename: str | None = None,
    ) -> str:
        """Presigned GET URL for a private artifact object.

        ``download_filename`` is served via the S3
        ``response-content-disposition`` override so a browser navigation (no
        ``Authorization`` header) still downloads with a friendly name.
        """

        params: dict[str, Any] = {
            "Bucket": self.connection_config.bucket,
            "Key": key,
        }
        if download_filename:
            safe = (
                download_filename.replace('"', "").replace("\r", "").replace("\n", "")
            )
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        try:
            return self.connection_config.client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=(
                    ttl_seconds
                    if ttl_seconds is not None
                    else presigned_get_ttl_from_env()
                ),
            )
        except (ClientError, BotoCoreError, NoCredentialsError) as exc:
            raise StorageUnavailable() from exc

    async def delete_object(self, key: str) -> bool:
        """Delete one object; missing keys raise :class:`FileObjectNotFound`.

        The purge task tolerates the missing case and still clears the
        artifact columns.
        """

        try:
            await to_thread(
                self.connection_config.client.delete_object,
                Bucket=self.connection_config.bucket,
                Key=key,
            )
            return True
        except ClientError as exc:
            code = str((exc.response or {}).get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "NoSuchBucket", "NotFound", "404"}:
                raise FileObjectNotFound() from exc
            raise StorageUnavailable() from exc
        except (BotoCoreError, NoCredentialsError) as exc:
            raise StorageUnavailable() from exc


__all__ = [
    "DEFAULT_ARTIFACT_RETENTION_DAYS",
    "DEFAULT_PRESIGNED_GET_TTL_SECONDS",
    "DEFAULT_REJECTED_FILES_PREFIX",
    "StorageService",
    "artifact_expires_at",
    "artifact_retention_days_from_env",
    "presigned_get_ttl_from_env",
    "rejection_key_for_file",
    "rejection_prefix_from_env",
]
