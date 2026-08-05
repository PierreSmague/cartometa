from __future__ import annotations

import hashlib
import os
from pathlib import Path

from cartometa.build.assets import content_hash

VARIANTES = ("t", "f")


def cle_de(source: bytes, signature: str) -> str:
    """Key of a source image for a given set of encoding parameters.

    The signature is part of the key: changing a width or the quality has to
    invalidate the whole cache, otherwise the build would serve images encoded
    according to settings that no longer exist.
    """
    empreinte = hashlib.sha256()
    empreinte.update(signature.encode("utf-8"))
    empreinte.update(b"\0")
    empreinte.update(source)
    return empreinte.hexdigest()


class ImageCache:
    """Cache of encoded images, persisted outside `dist/`.

    `dist/` is wiped on every build: the cache has to live elsewhere, otherwise
    it would vanish along with it every single time.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _dossier(self, cle: str) -> Path:
        # Fanned out over two characters: a single folder holding several
        # thousand entries walks badly on some file systems.
        return self.directory / cle[:2]

    def lire(self, cle: str, variante: str) -> bytes | None:
        """Encoded bytes, or None if absent — or damaged.

        The content fingerprint is written into the entry's name: re-checking it
        costs a sha256 that is needed elsewhere anyway, and it is the only way to
        tell a sound entry from one truncated by an interruption or a failing
        disk. An entry that does not match its fingerprint is treated as absent:
        the price is a re-encode, never a broken image in the published site.
        """
        for chemin in self._dossier(cle).glob(f"{cle}.{variante}.*.webp"):
            payload = chemin.read_bytes()
            if content_hash(payload) == chemin.name.split(".")[-2]:
                return payload
        return None

    def ecrire(self, cle: str, variante: str, payload: bytes) -> None:
        dossier = self._dossier(cle)
        dossier.mkdir(parents=True, exist_ok=True)
        chemin = dossier / f"{cle}.{variante}.{content_hash(payload)}.webp"
        # Atomic write: a half-written entry must never appear under its final
        # name, otherwise the next build would read it as if it were complete.
        temporaire = chemin.with_suffix(chemin.suffix + ".part")
        try:
            temporaire.write_bytes(payload)
            os.replace(temporaire, chemin)
        finally:
            if temporaire.exists():
                temporaire.unlink()
