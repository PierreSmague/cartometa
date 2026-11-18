import json

import numpy as np
import pytest
from shapely.geometry import Point, box

from cartometa.carmeta.footprint import (
    footprint_km,
    footprint_pieces,
    iou,
    pieces_geometry,
)
from cartometa.carmeta.zones import KM_PER_DEG_LAT, KM_PER_DEG_LON, build_frame, tag_zones
from cartometa.geo.reference import DATASET_NAME
from cartometa.review.pieces import resolve_pieces

LAT0, LNG0 = 10.0, 10.0
KX = KM_PER_DEG_LON * np.cos(np.radians(LAT0))


def _cloud(xy_km):
    """A frame over points given in km from (LAT0, LNG0), all carrying the tag."""
    xy = np.asarray(xy_km, dtype=float)
    frame = build_frame(LAT0 + xy[:, 1] / KM_PER_DEG_LAT, LNG0 + xy[:, 0] / KX)
    return frame, tag_zones(frame, np.arange(len(xy)), 30)


def _road(y_km, length=60, step=0.5, x0=0.0):
    return [(x0 + i * step, y_km) for i in range(length)]


def _block(x0, y0, side_km, step=0.5, hole=None):
    points = []
    count = int(side_km / step)
    for i in range(count):
        for j in range(count):
            x, y = x0 + i * step, y0 + j * step
            if hole and hole[0] <= x < hole[2] and hole[1] <= y < hole[3]:
                continue
            points.append((x, y))
    return points


def _polygons(geometry):
    return [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)


def test_two_neighbouring_roads_merge_into_one_footprint():
    # Link is 1.5 km (3 × 0.5): roads 4.5 km apart are 2 empty cells apart.
    frame, zones = _cloud(_road(0.2) + _road(4.7))
    assert zones.count == 2

    assert len(_polygons(footprint_km(frame, zones))) == 1


def test_two_distant_roads_stay_two_footprints():
    frame, zones = _cloud(_road(0.2) + _road(13.7))
    assert zones.count == 2

    assert len(_polygons(footprint_km(frame, zones))) == 2


def test_a_small_hole_is_filled_and_a_large_one_kept():
    link = 1.5
    small = (9.0, 9.0, 9.0 + 4 * link, 9.0 + 4 * link)        # 16 cells
    frame, zones = _cloud(_block(0, 0, 30, hole=small))
    assert all(len(p.interiors) == 0 for p in _polygons(footprint_km(frame, zones)))

    large = (6.0, 6.0, 6.0 + 10 * link, 6.0 + 10 * link)      # 100 cells
    frame, zones = _cloud(_block(0, 0, 30, hole=large))
    (polygon,) = _polygons(footprint_km(frame, zones))
    assert len(polygon.interiors) == 1


def test_every_zone_point_lies_inside_the_footprint():
    frame, zones = _cloud(_road(0.2) + _road(13.7) + _block(40, 0, 6))
    footprint = footprint_km(frame, zones)

    inside = [footprint.contains(Point(frame.x[i], frame.y[i])) for i in zones.points]
    assert all(inside)


def test_the_pieces_are_polygons_followed_by_a_clip():
    frame, zones = _cloud(_road(0.2) + _road(13.7))

    pieces = footprint_pieces(frame, zones)

    assert [p["kind"] for p in pieces] == ["polygon", "polygon", "clip"]
    ring = pieces[0]["ring"]
    assert all(9.9 < lon < 10.5 and 9.9 < lat < 10.3 for lon, lat in ring)
    # Rounded once, here: stored, cached and compared values are the same numbers.
    assert all(round(v, 5) == v for vertex in ring for v in vertex)


def test_the_review_resolves_the_pieces_and_clips_them_to_the_country(tmp_path):
    (tmp_path / DATASET_NAME).write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "properties": {"ISO_A2": "AA", "ISO_A2_EH": "AA"},
            # The country stops at latitude 10: the road at y = 0.2 km sits on
            # the border and half of its footprint falls outside.
            "geometry": {"type": "Polygon", "coordinates": [[
                [9.0, 10.0], [11.0, 10.0], [11.0, 11.0], [9.0, 11.0], [9.0, 10.0]]]},
        }],
    }), "utf-8")
    frame, zones = _cloud(_road(0.2))
    pieces = footprint_pieces(frame, zones)

    resolved = resolve_pieces(pieces, "AA", tmp_path)

    unclipped = pieces_geometry(pieces)
    assert 0 < resolved.area < unclipped.area
    assert resolved.bounds[1] == pytest.approx(10.0)


def test_a_footprint_across_the_antimeridian_is_cut_there():
    lat = np.full(80, -17.0)
    lng = np.concatenate([np.linspace(179.80, 179.995, 40),
                          np.linspace(-179.995, -179.80, 40)])
    frame = build_frame(lat, lng)
    zones = tag_zones(frame, np.arange(80), 30)

    pieces = footprint_pieces(frame, zones)

    rings = [p["ring"] for p in pieces if p["kind"] == "polygon"]
    assert len(rings) == 2
    assert all(-180 <= lon <= 180 for ring in rings for lon, _ in ring)
    # Each side of the line keeps its own polygon: none spans the planet.
    assert all(max(l for l, _ in r) - min(l for l, _ in r) < 1 for r in rings)


def test_no_zone_nothing_to_trace():
    frame, zones = _cloud([(i * 20.0, 0.0) for i in range(10)])

    with pytest.raises(ValueError, match="no zone"):
        footprint_km(frame, zones)


def test_iou():
    square = box(0, 0, 1, 1)

    assert iou(square, square) == 1.0
    assert iou(square, box(5, 5, 6, 6)) == 0.0
    assert iou(square, box(0.5, 0, 1.5, 1)) == pytest.approx(1 / 3)
    assert iou(box(0, 0, 0, 0), box(0, 0, 0, 0)) == 0.0


def test_pieces_geometry_ignores_the_clip_and_honours_holes():
    pieces = [
        {"kind": "polygon", "ring": [[0, 0], [4, 0], [4, 4], [0, 4]],
         "holes": [[[1, 1], [2, 1], [2, 2], [1, 2]]]},
        {"kind": "polygon", "ring": [[10, 0], [11, 0], [11, 1], [10, 1]]},
        {"kind": "clip"},
    ]

    assert pieces_geometry(pieces).area == pytest.approx(16 - 1 + 1)
