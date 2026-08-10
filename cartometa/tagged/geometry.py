from __future__ import annotations

import math

from shapely import concave_hull
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from cartometa.review.pieces import MAX_RING_POINTS

KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON = 111.320


def _projector(points):
    """(to_xy, to_wgs) for a local point cloud, in kilometres.

    A flat scaling by cos(mean latitude): at country scale and for buffers of
    250 m to 10 km the distortion is negligible, and it spares a pyproj
    dependency. Known limit, accepted: clouds straddling the antimeridian or a
    whole continent distort — the per-country split keeps real inputs local.
    """
    lat0 = sum(lat for lat, _ in points) / len(points)
    kx = KM_PER_DEG_LON * math.cos(math.radians(lat0))
    ky = KM_PER_DEG_LAT

    def to_xy(lng, lat):
        return (lng * kx, lat * ky)

    def to_wgs(x, y):
        return (x / kx, y / ky)

    return to_xy, to_wgs


def mst_edges(xy: list[tuple[float, float]]) -> list[tuple[int, int, float]]:
    """Minimum spanning tree (Prim, O(n²) pure Python), edges (i, j, km).

    ~7 M distance evaluations for the worst real tag (2 592 points): a few
    seconds, which does not justify a numpy dependency.
    """
    n = len(xy)
    if n < 2:
        return []
    in_tree = [False] * n
    dist = [math.inf] * n
    parent = [0] * n
    in_tree[0] = True
    for j in range(1, n):
        dist[j] = math.dist(xy[0], xy[j])
    edges = []
    for _ in range(n - 1):
        d, j = min(
            (d, j) for j, (d, seen) in enumerate(zip(dist, in_tree)) if not seen
        )
        in_tree[j] = True
        dist[j] = math.inf
        edges.append((parent[j], j, d))
        for k in range(n):
            if not in_tree[k]:
                dk = math.dist(xy[j], xy[k])
                if dk < dist[k]:
                    dist[k] = dk
                    parent[k] = j
    return edges


def _clusters(xy: list[tuple[float, float]], link_km: float) -> list[list[int]]:
    """Connected components of the MST once edges longer than link_km are cut."""
    parent = list(range(len(xy)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b, d in mst_edges(xy):
        if d <= link_km:
            parent[find(a)] = find(b)
    groups: dict[int, list[int]] = {}
    for i in range(len(xy)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def corridor_geometry(
    points, buffer_m: float = 250.0, link_km: float = 5.0
) -> BaseGeometry:
    """A faithful ribbon around the reconstructed route (width = 2 × buffer_m).

    MST edges longer than link_km are cut: they would bridge distinct road
    segments. A point left without any edge becomes a disc.
    """
    to_xy, to_wgs = _projector(points)
    xy = [to_xy(lng, lat) for lat, lng in points]
    edges = [e for e in mst_edges(xy) if e[2] <= link_km]
    linked = {i for a, b, _ in edges for i in (a, b)}
    parts: list[BaseGeometry] = [LineString([xy[a], xy[b]]) for a, b, _ in edges]
    parts += [Point(p) for i, p in enumerate(xy) if i not in linked]
    ribbon = unary_union(parts).buffer(buffer_m / 1000.0)
    return transform(to_wgs, ribbon)


def zone_geometry(
    points,
    hull_buffer_km: float = 10.0,
    link_km: float = 40.0,
    ratio: float = 0.4,
) -> BaseGeometry:
    """One inflated concave hull per cluster of points.

    Clusters of one or two points have no hull: the buffer alone gives a disc
    or a capsule.
    """
    to_xy, to_wgs = _projector(points)
    xy = [to_xy(lng, lat) for lat, lng in points]
    shapes = []
    for cluster in _clusters(xy, link_km):
        cloud = MultiPoint([xy[i] for i in cluster])
        core = concave_hull(cloud, ratio=ratio) if len(cluster) >= 3 else cloud
        shapes.append(core.buffer(hull_buffer_km))
    return transform(to_wgs, unary_union(shapes))


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon" and g.area > 0]


def geometry_to_pieces(geom: BaseGeometry, simplify_deg: float) -> list[dict]:
    """One `polygon` piece per polygon, rings open, capped at MAX_RING_POINTS.

    Simplified before conversion so the versioned geojson stays bounded; the
    tolerance doubles until every ring fits under resolve_pieces' safety rail —
    a corridor over thousands of points can exceed it at the first tolerance.
    """
    tolerance = simplify_deg
    for _ in range(12):
        simplified = geom.simplify(tolerance, preserve_topology=True)
        pieces = []
        fits = True
        for poly in _polygons(simplified):
            rings = [poly.exterior, *poly.interiors]
            if any(len(r.coords) - 1 > MAX_RING_POINTS for r in rings):
                fits = False
                break
            piece = {"kind": "polygon", "ring": [list(c) for c in poly.exterior.coords[:-1]]}
            holes = [
                [list(c) for c in interior.coords[:-1]]
                for interior in poly.interiors
                if len(interior.coords) - 1 >= 3
            ]
            if holes:
                piece["holes"] = holes
            pieces.append(piece)
        if fits and pieces:
            return pieces
        tolerance *= 2
    raise ValueError("geometry too dense: no tolerance fits under MAX_RING_POINTS")
