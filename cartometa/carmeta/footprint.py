"""From the zones of a tag to the pieces the review interface preloads."""
from __future__ import annotations

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from cartometa.carmeta.zones import KM_PER_DEG_LAT, Frame, Zones
from cartometa.review.pieces import CLIP
from cartometa.tagged.geometry import geometry_to_pieces

# Starting values: the maintainer validated the zones on the analysis grid,
# not the final shape of the polygon. All four are in link cells (side L) and
# are tuned by looking at real footprints in the review interface.
#
# Closing radius: fills the gaps between neighbouring roads.
CLOSING_RADIUS_CELLS = 2.0
# Interior holes smaller than this many cells are filled.
MAX_HOLE_CELLS = 25.0
# Final smoothing: dilation then simplification.
DILATE_CELLS = 0.5
SIMPLIFY_CELLS = 0.25

# Enough for a smooth outline; the default 16 quadruples the vertex count of
# every buffer for nothing at these scales.
_QUAD_SEGS = 4


def _cells_geometry(cells: np.ndarray, link: float) -> BaseGeometry:
    """Union of the occupied link cells, in km.

    Consecutive cells of a row are merged into one rectangle first: a tag of
    100 000 points occupies tens of thousands of cells, and uniting them one
    square at a time is what would make this slow.
    """
    order = np.lexsort((cells[:, 1], cells[:, 0]))
    rows, columns = cells[order, 0], cells[order, 1]
    breaks = np.nonzero((np.diff(rows) != 0) | (np.diff(columns) != 1))[0] + 1
    starts = np.concatenate([[0], breaks])
    ends = np.concatenate([breaks, [len(rows)]])
    runs = [
        box(columns[s] * link, rows[s] * link,
            (columns[e - 1] + 1) * link, (rows[s] + 1) * link)
        for s, e in zip(starts.tolist(), ends.tolist())
    ]
    return unary_union(runs)


def _without_small_holes(geometry: BaseGeometry, min_area: float) -> BaseGeometry:
    polygons = [geometry] if geometry.geom_type == "Polygon" else list(
        getattr(geometry, "geoms", []))
    filled = [
        Polygon(p.exterior, [h for h in p.interiors if Polygon(h).area >= min_area])
        for p in polygons if p.geom_type == "Polygon" and not p.is_empty
    ]
    return unary_union(filled)


def footprint_km(frame: Frame, zones: Zones) -> BaseGeometry:
    """The footprint in the frame's kilometres, before the trip back to WGS84."""
    if zones.count == 0:
        raise ValueError("no zone: nothing to trace")
    link = frame.link_km
    shape = _cells_geometry(zones.cells[:, :2], link)
    # Morphological closing, on the union of the zones rather than zone by
    # zone: two stretches of the same coverage a couple of cells apart are one
    # footprint for the player.
    radius = CLOSING_RADIUS_CELLS * link
    shape = shape.buffer(radius, quad_segs=_QUAD_SEGS).buffer(
        -radius, quad_segs=_QUAD_SEGS)
    shape = _without_small_holes(shape, MAX_HOLE_CELLS * link * link)
    shape = shape.buffer(DILATE_CELLS * link, quad_segs=_QUAD_SEGS)
    return shape.simplify(SIMPLIFY_CELLS * link, preserve_topology=True)


def to_wgs(frame: Frame, geometry: BaseGeometry) -> BaseGeometry:
    """Back from the frame's kilometres to longitude/latitude."""
    wgs = affinity.scale(geometry, xfact=1 / frame.kx, yfact=1 / KM_PER_DEG_LAT,
                         origin=(0, 0))
    if not frame.wrapped:
        return wgs
    # The frame shifted the western hemisphere by +360 to keep the country in
    # one piece; a footprint straddling the antimeridian is cut there and its
    # eastern part brought back, or its ring would run round the planet.
    west = wgs.intersection(box(-180, -90, 180, 90))
    east = affinity.translate(wgs.intersection(box(180, -90, 540, 90)), xoff=-360)
    return unary_union([part for part in (west, east) if not part.is_empty])


def _rounded(value):
    if isinstance(value, float):
        return round(value, 5)
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    return value


def footprint_pieces(frame: Frame, zones: Zones) -> list[dict]:
    """`polygon` pieces plus a `clip`: the borders are cut by resolve_pieces,
    on the very silhouette the review's F key uses.

    Rounded to 5 decimals here rather than left to save_geo: the cached
    analysis, the stored proposal and the baseline then all hold the same
    numbers, and comparing them is plain equality.
    """
    geometry = to_wgs(frame, footprint_km(frame, zones))
    tolerance = SIMPLIFY_CELLS * frame.link_km / KM_PER_DEG_LAT
    pieces = geometry_to_pieces(geometry, tolerance)
    return [_rounded(piece) for piece in pieces] + [{"kind": CLIP}]


def pieces_geometry(pieces: list[dict]) -> BaseGeometry:
    """Union of the `polygon` pieces, unclipped.

    The reference two computed footprints are compared on: clipping would make
    the comparison depend on the country outline, which is not what moved.
    """
    polygons = []
    for piece in pieces:
        if piece.get("kind") != "polygon":
            continue
        polygon = Polygon(piece["ring"], piece.get("holes") or [])
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if not polygon.is_empty:
            polygons.append(polygon)
    return unary_union(polygons)


def iou(a: BaseGeometry, b: BaseGeometry) -> float:
    """Intersection over union.

    Computed in degrees: a ratio of areas does not depend on the local scale,
    so there is no need to project.
    """
    union = a.union(b).area
    if union <= 0:
        return 0.0
    return float(a.intersection(b).area / union)
