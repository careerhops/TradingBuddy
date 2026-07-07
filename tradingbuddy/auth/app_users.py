from __future__ import annotations

import base64
import hashlib
import hmac
import os


HASH_ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 310_000
SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    if not password:
        raise ValueError("Password cannot be empty")
    salt = os.urandom(SALT_BYTES)
    digest = _pbkdf2(password, salt, iterations)
    return "$".join(
        (
            HASH_ALGORITHM,
            str(iterations),
            _b64encode(salt),
            _b64encode(digest),
        )
    )


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        iterations = int(iterations_text)
    except ValueError:
        return False
    if algorithm != HASH_ALGORITHM or iterations <= 0:
        return False

    try:
        salt = _b64decode(salt_text)
        expected_digest = _b64decode(digest_text)
    except ValueError:
        return False

    actual_digest = _pbkdf2(password, salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)


def _pbkdf2(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
