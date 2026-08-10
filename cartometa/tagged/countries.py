from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from cartometa.geo.reference import ensure_dataset

# Snapping radius for a point inside no polygon (sea, Natural Earth coastline
# gap): beyond ~10 km it is dropped rather than force-attached.
NEAREST_MAX_DEG = 0.09


class CountryIndex:
    """Point -> ISO alpha-2 code, from Natural Earth admin-0.

    Built once per import. The STRtree holds the *parts* of the multipolygons,
    not the whole countries: querying 5 000 points against entire geometries
    would drag every lookup through the full Russia polygon.
    """

    def __init__(self, cache_dir: Path) -> None:
        data = json.loads(ensure_dataset(cache_dir).read_text("utf-8"))
        self._codes: list[str] = []
        parts = []
        for feature in data["features"]:
            props = feature["properties"]
            code = props.get("ISO_A2_EH") or props.get("ISO_A2")
            # Natural Earth encodes a missing code as "-99".
            if not code or code == "-99":
                continue
            geom = shape(feature["geometry"])
            if not geom.is_valid:
                geom = geom.buffer(0)
            for part in geom.geoms if geom.geom_type == "MultiPolygon" else [geom]:
                parts.append(part)
                self._codes.append(code.upper())
        self._tree = STRtree(parts)

    def country_of(self, lat: float, lng: float) -> str | None:
        point = Point(lng, lat)
        hits = self._tree.query(point, predicate="intersects")
        if len(hits):
            return self._codes[hits[0]]
        near = self._tree.query_nearest(point, max_distance=NEAREST_MAX_DEG)
        if len(near):
            return self._codes[near[0]]
        return None
