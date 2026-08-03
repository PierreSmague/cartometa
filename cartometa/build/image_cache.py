from __future__ import annotations

import hashlib
import os
from pathlib import Path

from cartometa.build.assets import content_hash

VARIANTES = ("t", "f")


def cle_de(source: bytes, signature: str) -> str:
    """Clé d'une image source pour un jeu de paramètres d'encodage donné.

    La signature entre dans la clé : changer une largeur ou la qualité doit
    invalider tout le cache, sans quoi le build servirait des images encodées
    selon des réglages qui n'existent plus.
    """
    empreinte = hashlib.sha256()
    empreinte.update(signature.encode("utf-8"))
    empreinte.update(b"\0")
    empreinte.update(source)
    return empreinte.hexdigest()


class ImageCache:
    """Cache d'images encodées, persistant hors de `dist/`.

    `dist/` est rasé à chaque build : le cache doit vivre ailleurs, sinon il
    disparaîtrait avec lui à chaque fois.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _dossier(self, cle: str) -> Path:
        # Éclaté sur deux caractères : un seul dossier de plusieurs milliers
        # d'entrées se parcourt mal sur certains systèmes de fichiers.
        return self.directory / cle[:2]

    def lire(self, cle: str, variante: str) -> bytes | None:
        """Octets encodés, ou None si absents — ou abîmés.

        L'empreinte du contenu est inscrite dans le nom de l'entrée : la
        relire coûte un sha256 déjà nécessaire par ailleurs, et c'est le
        seul moyen de distinguer une entrée saine d'une entrée tronquée par
        une interruption ou un disque défaillant. Une entrée qui ne
        correspond pas à son empreinte est traitée comme absente : le prix
        est un réencodage, jamais une image cassée dans le site publié.
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
        # Écriture atomique : une entrée à moitié écrite ne doit jamais
        # apparaître sous son nom définitif, sinon le build suivant la lirait
        # comme si elle était complète.
        temporaire = chemin.with_suffix(chemin.suffix + ".part")
        try:
            temporaire.write_bytes(payload)
            os.replace(temporaire, chemin)
        finally:
            if temporaire.exists():
                temporaire.unlink()
