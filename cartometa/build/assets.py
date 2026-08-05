from __future__ import annotations

import hashlib
from pathlib import Path

# Eight hexadecimal characters: 4 billion values, plenty for a few thousand
# files, and a name that stays readable inside a URL.
HASH_LENGTH = 8


def content_hash(payload: bytes) -> str:
    """Short content fingerprint, the basis of the immutable cache."""
    return hashlib.sha256(payload).hexdigest()[:HASH_LENGTH]


def hashed_name(stem: str, suffix: str, payload: bytes) -> str:
    """`index` + `.json` + content → `index.a1b2c3d4.json`."""
    return f"{stem}.{content_hash(payload)}{suffix}"


def write_hashed(directory: Path, stem: str, suffix: str, payload: bytes) -> str:
    """Write the file under its fingerprinted name and return that name.

    Returns the name alone and not the path: the caller is the one that knows
    under which relative URL the file will be served.
    """
    directory.mkdir(parents=True, exist_ok=True)
    nom = hashed_name(stem, suffix, payload)
    (directory / nom).write_bytes(payload)
    return nom
