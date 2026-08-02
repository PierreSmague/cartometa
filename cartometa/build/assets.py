from __future__ import annotations

import hashlib
from pathlib import Path

# Huit caractères hexadécimaux : 4 milliards de valeurs, largement assez pour
# quelques milliers de fichiers, et un nom qui reste lisible dans une URL.
HASH_LENGTH = 8


def content_hash(payload: bytes) -> str:
    """Empreinte courte du contenu, base du cache immuable."""
    return hashlib.sha256(payload).hexdigest()[:HASH_LENGTH]


def hashed_name(stem: str, suffix: str, payload: bytes) -> str:
    """`index` + `.json` + contenu → `index.a1b2c3d4.json`."""
    return f"{stem}.{content_hash(payload)}{suffix}"


def write_hashed(directory: Path, stem: str, suffix: str, payload: bytes) -> str:
    """Écrit le fichier sous son nom empreinté et renvoie ce nom.

    Renvoie le nom seul et non le chemin : c'est l'appelant qui sait sous
    quelle URL relative le fichier sera servi.
    """
    directory.mkdir(parents=True, exist_ok=True)
    nom = hashed_name(stem, suffix, payload)
    (directory / nom).write_bytes(payload)
    return nom
