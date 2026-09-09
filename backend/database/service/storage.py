from backend.database.connection import StorageAsyncConnectionConfig
from datetime import datetime
from asyncio import to_thread
from typing import Any


class StorageService:
    def __init__(self, config: StorageAsyncConnectionConfig):
        self.connection_config = config

    def get_today_folder(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def get_presigned_url(self, object_key: str, content_type: str) -> str:
        return self.connection_config.client.generate_presigned_url(
            ClientMethod="put_object",
            ExpiresIn=60,
            Params={
                "Bucket": self.connection_config.bucket,
                "Key": f"{object_key}",
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
