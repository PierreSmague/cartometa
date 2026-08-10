import json
import math

import pytest

from cartometa.geo.reference import DATASET_NAME
from cartometa.review.pieces import MAX_RING_POINTS, PieceError, resolve_pieces


def _box(x0, y0, x1, y1):
    return {"type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


COUNTRIES = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"ISO_A2": "PL", "ISO_A2_EH": "PL", "NAME": "Poland"},
     "geometry": _box(14.0, 49.0, 24.0, 55.0)},
]}

REGIONS = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"code": "POL-1", "name": "Mazowieckie"},
     "geometry": _box(20.0, 51.0, 22.0, 53.0)},
    {"type": "Feature", "properties": {"code": "POL-2", "name": "Malopolskie"},
     "geometry": _box(19.0, 49.0, 21.0, 50.5)},
]}


@pytest.fixture
def cache_dir(tmp_path):
    (tmp_path / DATASET_NAME).write_text(json.dumps(COUNTRIES), "utf-8")
    (tmp_path / "admin1").mkdir()
    (tmp_path / "admin1" / "PL.geojson").write_text(json.dumps(REGIONS), "utf-8")
    return tmp_path


def test_rectangle(cache_dir):
    geom = resolve_pieces([{"kind": "rect", "bounds": [2.0, 48.0, 3.0, 49.0]}], "PL", cache_dir)

    assert geom.bounds == (2.0, 48.0, 3.0, 49.0)


def test_rectangle_whose_corners_are_given_backwards(cache_dir):
    """Two clicks on the map can arrive in any order."""
    geom = resolve_pieces([{"kind": "rect", "bounds": [3.0, 49.0, 2.0, 48.0]}], "PL", cache_dir)

    assert geom.bounds == (2.0, 48.0, 3.0, 49.0)


def test_whole_country(cache_dir):
    geom = resolve_pieces([{"kind": "country"}], "PL", cache_dir)

    assert geom.bounds == (14.0, 49.0, 24.0, 55.0)


def test_admin1_region(cache_dir):
    geom = resolve_pieces([{"kind": "admin1", "code": "POL-1"}], "PL", cache_dir)

    assert geom.bounds == (20.0, 51.0, 22.0, 53.0)


def test_a_freehand_outline_is_closed_automatically(cache_dir):
    ring = [[2.0, 48.0], [3.0, 48.0], [3.0, 49.0]]

    geom = resolve_pieces([{"kind": "polygon", "ring": ring}], "PL", cache_dir)

    assert geom.is_valid
    assert geom.area == pytest.approx(0.5)


def test_two_adjacent_regions_merge_into_one_polygon(cache_dir):
    geom = resolve_pieces([
        {"kind": "admin1", "code": "POL-1"},
        {"kind": "admin1", "code": "POL-2"},
    ], "PL", cache_dir)

    assert geom.bounds == (19.0, 49.0, 22.0, 53.0)


def test_disjoint_pieces_give_a_multipolygon(cache_dir):
    geom = resolve_pieces([
        {"kind": "rect", "bounds": [2.0, 48.0, 3.0, 49.0]},
        {"kind": "rect", "bounds": [10.0, 48.0, 11.0, 49.0]},
    ], "PL", cache_dir)

    assert geom.geom_type == "MultiPolygon"
    assert len(geom.geoms) == 2


def test_a_self_intersecting_outline_is_repaired(cache_dir):
    """A bow tie drawn with the mouse must not be rejected."""
    ring = [[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0]]

    geom = resolve_pieces([{"kind": "polygon", "ring": ring}], "PL", cache_dir)

    assert geom.is_valid
    assert geom.area > 0.0


def test_clipping_cuts_what_sticks_out_of_the_country(cache_dir):
    """The intended gesture: a wide rectangle that spills over, clipped to the borders."""
    geom = resolve_pieces([
        {"kind": "rect", "bounds": [10.0, 45.0, 20.0, 52.0]},
        {"kind": "clip"},
    ], "PL", cache_dir)

    # The country runs from 14/49 to 24/55: the west and south of the rectangle are cut.
    assert geom.bounds == (14.0, 49.0, 20.0, 52.0)


def test_clipping_has_no_effect_when_everything_is_inside(cache_dir):
    geom = resolve_pieces([
        {"kind": "rect", "bounds": [15.0, 50.0, 16.0, 51.0]},
        {"kind": "clip"},
    ], "PL", cache_dir)

    assert geom.bounds == (15.0, 50.0, 16.0, 51.0)


def test_the_position_of_the_clip_in_the_list_changes_nothing(cache_dir):
    """It is a modifier applied once at the end, not an operand."""
    avant = resolve_pieces([
        {"kind": "clip"},
        {"kind": "rect", "bounds": [10.0, 45.0, 20.0, 52.0]},
    ], "PL", cache_dir)
    apres = resolve_pieces([
        {"kind": "rect", "bounds": [10.0, 45.0, 20.0, 52.0]},
        {"kind": "clip"},
    ], "PL", cache_dir)

    assert avant.equals(apres)


def test_the_clip_applies_to_the_whole_union_not_to_the_last_piece(cache_dir):
    geom = resolve_pieces([
        {"kind": "rect", "bounds": [10.0, 45.0, 16.0, 52.0]},
        {"kind": "rect", "bounds": [22.0, 50.0, 30.0, 60.0]},
        {"kind": "clip"},
    ], "PL", cache_dir)

    assert geom.bounds == (14.0, 49.0, 24.0, 55.0)
    assert geom.geom_type == "MultiPolygon"


def test_clipping_an_area_entirely_outside_the_country_is_refused(cache_dir):
    with pytest.raises(PieceError, match="clipping to the borders"):
        resolve_pieces([
            {"kind": "rect", "bounds": [2.0, 40.0, 3.0, 41.0]},
            {"kind": "clip"},
        ], "PL", cache_dir)


def test_a_lone_clip_with_no_surface_is_refused(cache_dir):
    """`clip` brings no surface: it is not a footprint on its own."""
    with pytest.raises(PieceError, match="no area to clip"):
        resolve_pieces([{"kind": "clip"}], "PL", cache_dir)


def test_a_clip_that_merely_grazes_the_border_is_refused(cache_dir):
    """A rectangle flush against the western border: the intersection is a segment, not a
    surface, and shapely can return it as a GeometryCollection."""
    with pytest.raises(PieceError, match="clipping to the borders"):
        resolve_pieces([
            {"kind": "rect", "bounds": [10.0, 50.0, 14.0, 51.0]},
            {"kind": "clip"},
        ], "PL", cache_dir)


def test_an_empty_list_is_refused(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([], "PL", cache_dir)


def test_a_two_vertex_outline_is_refused(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "polygon", "ring": [[2.0, 48.0], [3.0, 48.0]]}], "PL", cache_dir)


def test_an_out_of_bounds_coordinate_is_refused(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "rect", "bounds": [2.0, 48.0, 3.0, 95.0]}], "PL", cache_dir)


def test_a_non_numeric_coordinate_is_refused(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "rect", "bounds": [2.0, 48.0, "est", 49.0]}], "PL", cache_dir)


def test_a_degenerate_rectangle_is_refused(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "rect", "bounds": [2.0, 48.0, 2.0, 49.0]}], "PL", cache_dir)


def test_an_unknown_piece_type_is_refused(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "cercle", "radius_km": 25}], "PL", cache_dir)


def test_an_unknown_region_code_is_refused(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "admin1", "code": "POL-99"}], "PL", cache_dir)


def test_a_country_absent_from_natural_earth_is_refused(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "country"}], "ZZ", cache_dir)


def test_an_overlong_outline_is_refused(cache_dir):
    # Generate a ring with MAX_RING_POINTS + 1 vertices on a circle (non-collinear).
    n = MAX_RING_POINTS + 1
    ring = [[10.0 * math.cos(i * 2 * math.pi / n), 10.0 * math.sin(i * 2 * math.pi / n)] for i in range(n)]

    with pytest.raises(PieceError, match="needs between.*and.*vertices"):
        resolve_pieces([{"kind": "polygon", "ring": ring}], "PL", cache_dir)


def test_a_polygon_piece_can_carry_holes(tmp_path):
    piece = {
        "kind": "polygon",
        "ring": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
        "holes": [[[4.0, 4.0], [6.0, 4.0], [6.0, 6.0], [4.0, 6.0]]],
    }
    geometry = resolve_pieces([piece], "PL", tmp_path)
    # 10×10 moins le trou 2×2.
    assert geometry.area == pytest.approx(96.0)


def test_a_hole_must_be_a_valid_ring(tmp_path):
    piece = {
        "kind": "polygon",
        "ring": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
        "holes": [[[4.0, 4.0], [6.0, 4.0]]],  # deux sommets : pas un anneau
    }
    with pytest.raises(PieceError):
        resolve_pieces([piece], "PL", tmp_path)


def test_holes_default_to_absent(tmp_path):
    # Le dessin à la main n'envoie jamais `holes` : l'absence du champ est la norme.
    piece = {"kind": "polygon", "ring": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]}
    geometry = resolve_pieces([piece], "PL", tmp_path)
    assert geometry.area == pytest.approx(50.0)
