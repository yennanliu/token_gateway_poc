"""API key generation and hashing.

Keys look like ``atp-<62 base62 chars>``. We store only the SHA-256 hash and a
short display prefix; the raw key is shown to the user exactly once.
"""

from __future__ import annotations

import hashlib
import secrets

KEY_PREFIX = "atp-"
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_BODY_LEN = 62


def generate_key() -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(_BODY_LEN))
    return f"{KEY_PREFIX}{body}"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def display_prefix(raw: str) -> str:
    """A short, safe-to-show identifier, e.g. ``atp-AbCdEfGh``."""
    return raw[: len(KEY_PREFIX) + 8]
