"""Password hashing.

Uses ``bcrypt`` directly rather than going through ``passlib`` — passlib
has been effectively unmaintained since 2020 and its bcrypt backend
breaks on bcrypt>=4.1 (it probes a removed ``__about__`` attribute).
Calling bcrypt directly is one function each way and removes that
fragile dependency entirely.
"""

from __future__ import annotations

import bcrypt

_BCRYPT_MAX_BYTES = 72  # bcrypt silently truncates beyond this; we reject instead.


def hash_password(plain_password: str) -> str:
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > _BCRYPT_MAX_BYTES:
        raise ValueError("Password exceeds the maximum supported length.")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed stored hash — treat as a verification failure, not a crash.
        return False
