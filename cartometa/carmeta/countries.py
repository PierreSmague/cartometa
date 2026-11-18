from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

from cartometa.geo.reference import ensure_dataset
from cartometa.tagged.countries import NEAREST_MAX_DEG


class CountryAssigner:
    """Points -> ISO alpha-2 codes, from Natural Earth admin-0, by the array.

    Same rule as `cartometa.tagged.countries.CountryIndex` — inside a country,
    else the nearest one within ~10 km for coastal points — but vectorised:
    `CountryIndex.country_of` one point at a time is too slow for the 850 000
    points of a single carmeta file.
    """

    def __init__(self, cache_dir: Path) -> None:
        data = json.loads(ensure_dataset(cache_dir).read_text("utf-8"))
        self.codes: list[str] = []
        self._geometries = []
        for feature in data["features"]:
            props = feature["properties"]
            code = props.get("ISO_A2_EH") or props.get("ISO_A2")
            # Natural Earth encodes a missing code as "-99".
            if not code or code == "-99":
                continue
            geometry = shape(feature["geometry"])
            if not geometry.is_valid:
                geometry = geometry.buffer(0)
            shapely.prepare(geometry)
            self.codes.append(code.upper())
            self._geometries.append(geometry)
        self._bounds = np.array([g.bounds for g in self._geometries]).reshape(-1, 4)
        self._tree = STRtree(self._geometries)
        self.iso = frozenset(self.codes)

    def assign(self, lat: np.ndarray, lng: np.ndarray) -> np.ndarray:
        """Index into `codes` for each point, −1 for a point in no country."""
        lat = np.asarray(lat, dtype=np.float64)
        lng = np.asarray(lng, dtype=np.float64)
        out = np.full(len(lat), -1, dtype=np.int32)
        if len(lat) == 0:
            return out
        bounds = self._bounds
        candidates = np.nonzero(
            (bounds[:, 0] <= lng.max()) & (bounds[:, 2] >= lng.min())
            & (bounds[:, 1] <= lat.max()) & (bounds[:, 3] >= lat.min())
        )[0]
        for country in candidates:
            todo = np.nonzero(out < 0)[0]
            if not len(todo):
                break
            west, south, east, north = bounds[country]
            inside_box = todo[
                (lng[todo] >= west) & (lng[todo] <= east)
                & (lat[todo] >= south) & (lat[todo] <= north)
            ]
            if not len(inside_box):
                continue
            # `intersects`, not `contains`: a point exactly on a border belongs
            # to a country, as it does for CountryIndex.
            hit = shapely.intersects_xy(
                self._geometries[country], lng[inside_box], lat[inside_box])
            out[inside_box[hit]] = country
        left = np.nonzero(out < 0)[0]
        if len(left):
            points = shapely.points(lng[left], lat[left])
            near_point, near_country = self._tree.query_nearest(
                points, max_distance=NEAREST_MAX_DEG)
            # query_nearest returns every tie: keep the first country per point.
            first = np.unique(near_point, return_index=True)[1]
            out[left[near_point[first]]] = near_country[first]
        return out
