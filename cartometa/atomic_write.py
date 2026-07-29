from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, payload: Any, *, indent: int | None = 2) -> None:
    """Écrit `payload` en JSON à `path` par fichier temporaire puis remplacement.

    Une interruption (coupure, Ctrl-C, disque plein) en plein milieu de
    l'écriture ne doit jamais laisser `path` tronqué ou corrompu : le fichier
    temporaire, lui, peut rester à moitié écrit, mais `path` n'est remplacé
    qu'une fois l'écriture terminée avec succès (`os.replace` est atomique
    sur le même volume).

    Utilisé à la fois par le serveur de revue (`cartometa/review/server.py`)
    et par la construction des géométries (`cartometa/geo/cli.py`) : ce
    dernier fichier porte, une fois la revue commencée, un travail humain
    irremplaçable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=indent, ensure_ascii=False), "utf-8")
    os.replace(temporary, path)
