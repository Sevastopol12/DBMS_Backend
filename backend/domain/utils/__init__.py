import base64
import json

from datetime import datetime
from zoneinfo import ZoneInfo
from hashlib import sha3_256
from io import BytesIO
from typing import Any
from pathlib import Path


def to_buffer(hashed_content: str):
    raw_bytes: bytes = base64.b64decode(hashed_content)
    return BytesIO(raw_bytes)


def decode_content(encoded_bytes: str) -> bytes:
    return base64.urlsafe_b64decode(encoded_bytes)


def hash_content(encoded_bytes: str) -> str:
    sha_object = sha3_256()
    sha_object.update(encoded_bytes.encode())

    return sha_object.hexdigest()


def get_current_timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d %H:%M:%S")


__all__ = [
    "to_buffer",
    "decode_content",
    "hash_content",
    "get_current_timestamp",
]
