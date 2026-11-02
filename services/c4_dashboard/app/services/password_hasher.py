"""bcrypt password hashing with a constant-time verify path."""

from __future__ import annotations

import bcrypt

# A dummy hash used when the user is not found, so the timing of the
# "wrong password" branch matches the "user exists" branch (contracts §4.1).
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str | None) -> bool:
    if hashed is None:
        # Still do a bcrypt comparison to keep the timing similar.
        bcrypt.checkpw(plain.encode(), _DUMMY_HASH)
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False
