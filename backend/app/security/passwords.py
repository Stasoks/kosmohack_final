from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type


hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, type=Type.ID)


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
