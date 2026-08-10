from __future__ import annotations

from pathlib import Path
from typing import Any

from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from cartometa.geo.admin1 import region_geometry
from cartometa.geo.reference import country_geometry

MIN_RING_POINTS = 3
# A hand-drawn outline has a few dozen vertices; an imported corridor
# (cartometa-import-tagged) has thousands. The cap is still not an ergonomic
# limit but a safety rail: it stops a misbehaving client from running shapely
# over an endless list.
MAX_RING_POINTS = 20_000

# The only "piece" that is not a surface to unite but a modifier applied to the
# union: it clips the result to the country borders.
CLIP = "clip"


class PieceError(ValueError):
    """Area piece that is unreadable, invalid, or outside earthly bounds."""


def _check_lonlat(lon: Any, lat: Any) -> tuple[float, float]:
    try:
        x, y = float(lon), float(lat)
    except (TypeError, ValueError):
        raise PieceError(f"non-numeric coordinate: ({lon!r}, {lat!r})") from None
    if not (-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0):
        raise PieceError(f"coordinate outside the WGS84 bounds: ({x}, {y})")
    return x, y


def _ring_points(ring: Any, label: str) -> list[tuple[float, float]]:
    if not isinstance(ring, (list, tuple)):
        raise PieceError(f"an outline needs {label} = [[lon, lat], ...]")
    if not (MIN_RING_POINTS <= len(ring) <= MAX_RING_POINTS):
        raise PieceError(
            f"a {label} needs between {MIN_RING_POINTS} and {MAX_RING_POINTS} "
            f"vertices, got {len(ring)}"
        )
    points = []
    for vertex in ring:
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 2:
            raise PieceError(f"unreadable vertex: {vertex!r}")
        points.append(_check_lonlat(vertex[0], vertex[1]))
    return points


def _rectangle(piece: dict) -> BaseGeometry:
    bounds = piece.get("bounds")
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise PieceError("a rectangle needs bounds = [west, south, east, north]")
    west, south = _check_lonlat(bounds[0], bounds[1])
    east, north = _check_lonlat(bounds[2], bounds[3])
    # The two clicks arrive in the order the human made them, not in geographic
    # order: we normalise rather than refuse.
    west, east = min(west, east), max(west, east)
    south, north = min(south, north), max(south, north)
    if west == east or south == north:
        raise PieceError("rectangle with zero area")
    return box(west, south, east, north)


def _contour(piece: dict) -> BaseGeometry:
    points = _ring_points(piece.get("ring"), "ring")
    holes = piece.get("holes") or []
    if not isinstance(holes, (list, tuple)):
        raise PieceError("holes must be a list of rings")
    shells = [_ring_points(hole, "hole") for hole in holes]

    geom = Polygon(points, shells)
    if not geom.is_valid:
        # An outline drawn with the mouse self-intersects easily. `buffer(0)`
        # repairs it without betraying the intent — the same treatment as damaged
        # Natural Earth outlines (cf. country_geometry).
        geom = geom.buffer(0)
    if geom.is_empty or geom.area <= 0.0:
        raise PieceError("outline with zero area")
    return geom


def _region(piece: dict, country: str, cache_dir: Path) -> BaseGeometry:
    code = piece.get("code")
    if not isinstance(code, str) or not code:
        raise PieceError("an admin1 piece needs the region code")
    try:
        return region_geometry(country, code, cache_dir)
    except KeyError as exc:
        raise PieceError(str(exc)) from None


def _country(country: str, cache_dir: Path) -> BaseGeometry:
    try:
        return country_geometry(country, cache_dir)
    except KeyError as exc:
        raise PieceError(str(exc)) from None


def _clip_to_country(union: BaseGeometry, country: str, cache_dir: Path) -> BaseGeometry:
    clipped = union.intersection(_country(country, cache_dir))
    if clipped.geom_type == "GeometryCollection":
        # An intersection can yield bits with no area — a rectangle grazing the
        # border gives a segment. Only what has area is a footprint; the rest is
        # geometric noise to throw away.
        clipped = unary_union([part for part in clipped.geoms if part.area > 0.0])
    if clipped.is_empty or clipped.area <= 0.0:
        raise PieceError(
            "clipping to the borders leaves no area: "
            "the pieces laid down are entirely outside the country"
        )
    return clipped


def resolve_pieces(pieces: list[dict], country: str, cache_dir: Path) -> BaseGeometry:
    """Union of an area's pieces, resolved server-side.

    The client only ever sends descriptors: `{"kind": "country"}` or
    `{"kind": "admin1", "code": …}` are resolved here from Natural Earth, never
    received as coordinates. So a published silhouette is always the reference
    data's, whatever the browser happened to display.

    `{"kind": "clip"}` is the only descriptor that brings no surface: it clips the
    union to the country silhouette. Its position in the list is irrelevant — it
    applies once, at the end.
    """
    if not isinstance(pieces, (list, tuple)) or not pieces:
        raise PieceError("no piece: there is nothing to save")

    geometries = []
    clip = False
    for piece in pieces:
        if not isinstance(piece, dict):
            raise PieceError(f"unreadable piece: {piece!r}")
        kind = piece.get("kind")
        if kind == CLIP:
            clip = True
        elif kind == "country":
            geometries.append(_country(country, cache_dir))
        elif kind == "admin1":
            geometries.append(_region(piece, country, cache_dir))
        elif kind == "rect":
            geometries.append(_rectangle(piece))
        elif kind == "polygon":
            geometries.append(_contour(piece))
        else:
            raise PieceError(f"unknown piece type: {kind!r}")

    if not geometries:
        raise PieceError("clipping is not a footprint: no area to clip")

    union = unary_union(geometries)
    if union.is_empty or not union.is_valid or union.area <= 0.0:
        raise PieceError("the union of the pieces yields no valid area")
    return _clip_to_country(union, country, cache_dir) if clip else union
