from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from cartometa.atomic_write import write_json_atomic
from cartometa.geo.reference import Downloader, ensure_file, urlretrieve

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
    """Reduce the world dataset to one country's regions, properties included.

    The source file weighs 41 MB and carries about a hundred fields per region,
    including translations of the name into twenty languages. We keep only the code
    and one label: that is what makes the per-country cache light enough to be sent
    to the browser as-is.
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
    iso_a2: str, cache_dir: Path, downloader: Downloader = urlretrieve
) -> dict:
    """The country's admin-1 regions, as a GeoJSON FeatureCollection.

    On the first call for a country, the world dataset is downloaded then reduced
    into `cache_dir/admin1/<CC>.geojson`. Later calls no longer touch the big file
    — not even its existence.
    """
    iso = iso_a2.upper()
    path = _country_cache(cache_dir, iso)
    if not path.exists():
        source_path = ensure_file(ADMIN1_URL, ADMIN1_NAME, cache_dir, downloader)
        extracted = _extract(json.loads(source_path.read_text("utf-8")), iso)
        if not extracted["features"]:
            # Writing an empty cache would condemn the country: never another
            # attempt, and an incomprehensible error message.
            raise KeyError(f"no admin-1 region for {iso} in Natural Earth")
        write_json_atomic(path, extracted, indent=None)
    return _load(str(path))


@lru_cache(maxsize=512)
def region_geometry(iso_a2: str, code: str, cache_dir: Path) -> BaseGeometry:
    """Outline of a region designated by its Natural Earth `adm1_code`.

    Memoized: callers must treat the returned geometry as immutable.
    """
    for feature in country_regions(iso_a2, cache_dir)["features"]:
        if feature["properties"]["code"] == code:
            geom = shape(feature["geometry"])
            return geom if geom.is_valid else geom.buffer(0)
    raise KeyError(f"unknown admin-1 region for {iso_a2.upper()}: {code!r}")
