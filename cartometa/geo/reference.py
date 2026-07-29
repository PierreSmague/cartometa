from __future__ import annotations

import json
import os
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Callable

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

DATASET_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_admin_0_countries.geojson"
)
DATASET_NAME = "ne_10m_admin_0_countries.geojson"

Downloader = Callable[[str, Path], None]


def _urlretrieve(url: str, dest: Path) -> None:
    urllib.request.urlretrieve(url, dest)


def ensure_dataset(cache_dir: Path, downloader: Downloader = _urlretrieve) -> Path:
    path = cache_dir / DATASET_NAME
    if not path.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".part")
        try:
            downloader(DATASET_URL, tmp_path)
            os.replace(tmp_path, path)
        finally:
            # Un téléchargement interrompu (réseau, Ctrl-C, disque plein) ne doit
            # jamais laisser de fichier partiel au chemin final, ni de résidu
            # temporaire : sinon les exécutions suivantes échoueraient sur une
            # erreur JSON obscure sans jamais retenter le téléchargement.
            if tmp_path.exists():
                tmp_path.unlink()
    return path


@lru_cache(maxsize=8)
def _load(path_str: str) -> dict:
    return json.loads(Path(path_str).read_text("utf-8"))


_NAME_FIELDS = ("NAME", "NAME_LONG", "NAME_EN", "ADMIN", "FORMAL_EN")


def _normalize_name(value: str) -> str:
    """Réduit un nom de pays à sa forme comparable: minuscules, mots seuls."""
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def country_code_for_name(name: str, cache_dir: Path) -> str | None:
    """Code ISO 3166-1 alpha-2 d'un pays désigné par son nom (ou son slug).

    Sert à déduire le code pays du slug d'URL Plonk It ("botswana" → "BW"),
    pour qu'ajouter un pays ne demande aucune modification du code. Renvoie
    None si aucun nom Natural Earth ne correspond exactement — l'appelant
    doit alors demander le code explicitement plutôt que de deviner.
    """
    target = _normalize_name(name)
    data = _load(str(ensure_dataset(cache_dir)))
    for feature in data["features"]:
        props = feature["properties"]
        for field in _NAME_FIELDS:
            value = props.get(field)
            if value and _normalize_name(value) == target:
                code = props.get("ISO_A2_EH") or props.get("ISO_A2")
                # Natural Earth encode l'absence de code par "-99".
                if code and code != "-99":
                    return code.upper()
    return None


def country_geometry(iso_a2: str, cache_dir: Path) -> BaseGeometry:
    """Contour Natural Earth 1:10m du pays, en WGS84."""
    data = _load(str(ensure_dataset(cache_dir)))
    for feature in data["features"]:
        props = feature["properties"]
        codes = {props.get("ISO_A2"), props.get("ISO_A2_EH")}
        if iso_a2.upper() in codes:
            geom = shape(feature["geometry"])
            return geom if geom.is_valid else geom.buffer(0)
    raise KeyError(f"pays introuvable dans Natural Earth: {iso_a2}")
