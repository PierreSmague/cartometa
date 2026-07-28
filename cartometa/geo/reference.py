from __future__ import annotations

import json
import urllib.request
from functools import lru_cache
from pathlib import Path

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

DATASET_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_admin_0_countries.geojson"
)
DATASET_NAME = "ne_10m_admin_0_countries.geojson"


def ensure_dataset(cache_dir: Path) -> Path:
    path = cache_dir / DATASET_NAME
    if not path.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(DATASET_URL, path)
    return path


@lru_cache(maxsize=8)
def _load(path_str: str) -> dict:
    return json.loads(Path(path_str).read_text("utf-8"))


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
