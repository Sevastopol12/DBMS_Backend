import os
import asyncio
import logging

from boto3 import client
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
)
from dataclasses import dataclass, field

from backend.database.errors import StorageUnavailable

from dotenv import load_dotenv

load_dotenv()


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StorageAsyncConnectionConfig:
    client: BaseClient
    bucket: str
    supported_format: dict[str, str] = field(
        default_factory=lambda: {
            "csv": "text/csv",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    )


def get_storage_config(
    *,
    max_pool_connections: int | None = None,
    connect_timeout: float | None = None,
    read_timeout: float | None = None,
) -> StorageAsyncConnectionConfig:
    config_kwargs = {"signature_version": "s3v4"}
    if max_pool_connections is not None:
        config_kwargs["max_pool_connections"] = max_pool_connections
    if connect_timeout is not None:
        config_kwargs["connect_timeout"] = connect_timeout
    if read_timeout is not None:
        config_kwargs["read_timeout"] = read_timeout

    s3_client = client(
        "s3",
        aws_access_key_id=os.getenv("STORAGE_KEY"),
        aws_secret_access_key=os.getenv("STORAGE_SECRET"),
        endpoint_url=os.getenv("STORAGE_ENDPOINT"),
        region_name=os.getenv("STORAGE_REGION"),
        config=Config(**config_kwargs),
    )

    bucket = os.getenv("STAGING_BUCKET")

    return StorageAsyncConnectionConfig(client=s3_client, bucket=bucket)


def storage_settings_from_env() -> dict:
    return {
        "max_pool_connections": int(os.getenv("S3_MAX_POOL_CONNECTIONS", "20")),
        "connect_timeout": float(os.getenv("S3_CONNECT_TIMEOUT", "5")),
        "read_timeout": float(os.getenv("S3_READ_TIMEOUT", "60")),
    }


async def probe_storage(config: StorageAsyncConnectionConfig) -> None:
    try:
        await asyncio.to_thread(config.client.head_bucket, Bucket=config.bucket)
    except ClientError as exc:
        response = exc.response or {}
        error = response.get("Error", {})
        code = str(error.get("Code", ""))
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 403 or code in {"403", "AccessDenied"}:
            logger.warning("Object storage access denied while probing bucket")
            return
        if status == 404 or code in {"404", "NoSuchBucket"}:
            raise StorageUnavailable() from exc
        raise
    except (EndpointConnectionError, ConnectTimeoutError, NoCredentialsError) as exc:
        raise StorageUnavailable() from exc


def close_storage(config: StorageAsyncConnectionConfig) -> None:
    config.client.close()
