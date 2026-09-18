from datetime import datetime
from zoneinfo import ZoneInfo
from asyncio import to_thread
from typing import Any

from botocore.exceptions import ClientError

from backend.database.connection import StorageAsyncConnectionConfig
from backend.database.errors import FileObjectNotFound


class StorageService:
    def __init__(self, config: StorageAsyncConnectionConfig):
        self.connection_config = config

    def get_today_folder(self) -> str:
        return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d")

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

    def get_presigned_post(self, filename: str, content_type: str) -> dict[str, Any]:
        return self.connection_config.client.generate_presigned_post(
            ExpiresIn=60,
            Bucket=self.connection_config.bucket,
            Key=f"{self.get_today_folder}/{filename}",
            Fields={"Content-Type": content_type},
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

            return None
