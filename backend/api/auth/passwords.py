import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

_hasher = PasswordHasher()

DUMMY_HASH = _hasher.hash("dummy_password")


async def verify_password(hash_str: str, password: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher.verify(hash_str, password)
        except (VerifyMismatchError, InvalidHash):
            return False

    return await asyncio.to_thread(_verify)


async def needs_rehash(hash_str: str) -> bool:
    return await asyncio.to_thread(_hasher.check_needs_rehash, hash_str)


def hash_password(password: str) -> str:
    return _hasher.hash(password)
