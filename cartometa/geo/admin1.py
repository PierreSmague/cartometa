from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from cartometa.atomic_write import write_json_atomic
from cartometa.geo.reference import Downloader, _urlretrieve, ensure_file

ADMIN1_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_admin_1_states_provinces.geojson"
)
ADMIN1_NAME = "ne_10m_admin_1_states_provinces.geojson"


def _country_cache(cache_dir: Path, iso_a2: str) -> Path:
    return cache_dir / "admin1" / f"{iso_a2}.geojson"


@lru_cache(maxsize=8)
def _load(path_str: str) -> dict:
    return json.loads(Path(path_str).read_text("utf-8"))


def _extract(source: dict, iso_a2: str) -> dict:
    """Réduit le dataset mondial aux régions d'un pays, propriétés comprises.

    Le fichier source pèse 41 Mo et porte une centaine de champs par région,
    dont les traductions du nom dans vingt langues. On n'en garde que le code
    et un libellé : c'est ce qui rend le cache par pays assez léger pour être
    envoyé tel quel au navigateur.
    """
    features = []
    for feature in source["features"]:
        props = feature["properties"]
        if (props.get("iso_a2") or "").upper() != iso_a2:
            continue
        name = props.get("name") or props.get("name_en") or props["adm1_code"]
        features.append({
            "type": "Feature",
            "properties": {"code": props["adm1_code"], "name": name},
            "geometry": feature["geometry"],
        })
    return {"type": "FeatureCollection", "features": features}


def country_regions(
    iso_a2: str, cache_dir: Path, downloader: Downloader = _urlretrieve
) -> dict:
    """Régions admin-1 du pays, en FeatureCollection GeoJSON.

    Au premier appel sur un pays, le dataset mondial est téléchargé puis
    réduit dans `cache_dir/admin1/<CC>.geojson`. Les appels suivants ne
    touchent plus au gros fichier — ni même à son existence.
    """
    iso = iso_a2.upper()
    path = _country_cache(cache_dir, iso)
    if not path.exists():
        source_path = ensure_file(ADMIN1_URL, ADMIN1_NAME, cache_dir, downloader)
        extracted = _extract(json.loads(source_path.read_text("utf-8")), iso)
        if not extracted["features"]:
            # Écrire un cache vide condamnerait le pays : plus jamais de
            # nouvelle tentative, et un message d'erreur incompréhensible.
            raise KeyError(f"aucune région admin-1 pour {iso} dans Natural Earth")
        write_json_atomic(path, extracted, indent=None)
    return _load(str(path))


def region_geometry(iso_a2: str, code: str, cache_dir: Path) -> BaseGeometry:
    """Contour d'une région désignée par son `adm1_code` Natural Earth."""
    for feature in country_regions(iso_a2, cache_dir)["features"]:
        if feature["properties"]["code"] == code:
            geom = shape(feature["geometry"])
            return geom if geom.is_valid else geom.buffer(0)
    raise KeyError(f"région admin-1 inconnue pour {iso_a2.upper()} : {code!r}")
