import base64
import re

import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
from hashlib import sha3_256
from io import BytesIO


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


_SEPARATORS = re.compile(r"[^a-z0-9]+")


def normalize_column_name(value: object) -> str:
    if not value:
        return ""
    text = value.strip().lower()
    # Decompose unicode characters into base + accent
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    # Replace non-alphanumeric with underscores
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


__all__ = [
    "to_buffer",
    "decode_content",
    "hash_content",
    "get_current_timestamp",
    "normalize_column_name",
]
