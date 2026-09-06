import os

from boto3 import client
from botocore.client import BaseClient
from botocore.config import Config
from dataclasses import dataclass, field


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


def get_storage_config() -> StorageAsyncConnectionConfig:
    s3_client = client(
        "s3",
        aws_access_key_id=os.getenv("STORAGE_KEY"),
        aws_secret_access_key=os.getenv("STORAGE_SECRET"),
        endpoint_url=os.getenv("STORAGE_ENDPOINT"),
        region_name=os.getenv("STORAGE_REGION"),
        config=Config(signature_version="s3v4"),
    )

    bucket = os.getenv("STAGING_BUCKET")

    return StorageAsyncConnectionConfig(client=s3_client, bucket=bucket)
