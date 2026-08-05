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


def urlretrieve(url: str, dest: Path) -> None:
    urllib.request.urlretrieve(url, dest)


def ensure_file(
    url: str, name: str, cache_dir: Path, downloader: Downloader = urlretrieve
) -> Path:
    """Download `url` into `cache_dir / name` if it is not already there.

    Shared between the countries dataset (admin-0) and the regions one (admin-1):
    both come from the same Natural Earth repository and have the same robustness
    constraints.
    """
    path = cache_dir / name
    if path.exists():
        return path
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".part")
    try:
        downloader(url, tmp_path)
        os.replace(tmp_path, path)
    finally:
        # An interrupted download (network, Ctrl-C, full disk) must never leave a
        # partial file at the final path, nor a temporary leftover: otherwise later
        # runs would fail on an obscure JSON error without ever retrying the
        # download.
        if tmp_path.exists():
            tmp_path.unlink()
    return path


def ensure_dataset(cache_dir: Path, downloader: Downloader = urlretrieve) -> Path:
    return ensure_file(DATASET_URL, DATASET_NAME, cache_dir, downloader)


@lru_cache(maxsize=8)
def _load(path_str: str) -> dict:
    return json.loads(Path(path_str).read_text("utf-8"))


_NAME_FIELDS = ("NAME", "NAME_LONG", "NAME_EN", "ADMIN", "FORMAL_EN")


def _normalize_name(value: str) -> str:
    """Reduce a country name to its comparable form: lowercase, bare words."""
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def country_code_for_name(name: str, cache_dir: Path) -> str | None:
    """ISO 3166-1 alpha-2 code of a country designated by its name (or its slug).

    Used to derive the country code from the Plonk It URL slug ("botswana" → "BW"),
    so that adding a country requires no code change. Returns None if no Natural
    Earth name matches exactly — the caller then has to ask for the code explicitly
    rather than guess.
    """
    target = _normalize_name(name)
    data = _load(str(ensure_dataset(cache_dir)))
    for feature in data["features"]:
        props = feature["properties"]
        for field in _NAME_FIELDS:
            value = props.get(field)
            if value and _normalize_name(value) == target:
                code = props.get("ISO_A2_EH") or props.get("ISO_A2")
                # Natural Earth encodes a missing code as "-99".
                if code and code != "-99":
                    return code.upper()
    return None


def country_geometry(iso_a2: str, cache_dir: Path) -> BaseGeometry:
    """Natural Earth 1:10m outline of the country, in WGS84."""
    data = _load(str(ensure_dataset(cache_dir)))
    for feature in data["features"]:
        props = feature["properties"]
        codes = {props.get("ISO_A2"), props.get("ISO_A2_EH")}
        if iso_a2.upper() in codes:
            geom = shape(feature["geometry"])
            return geom if geom.is_valid else geom.buffer(0)
    raise KeyError(f"country not found in Natural Earth: {iso_a2}")
