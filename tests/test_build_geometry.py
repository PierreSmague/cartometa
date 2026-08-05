import math

import pytest
from shapely.geometry import Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry

from cartometa.build.geometry import (
    DEFAULT_TOLERANCE,
    SIZE_DIVISOR,
    area_ratio,
    effective_tolerance,
    hausdorff,
    part_bboxes,
    round_coordinates,
    simplify_geometry,
)


def _rectangle(x: float, y: float, largeur: float, hauteur: float, pas: int = 1) -> dict:
    """A rectangle whose sides carry `pas` aligned intermediate vertices.

    The intermediate points are exactly collinear: Douglas-Peucker must remove them
    whatever the tolerance, which gives a predictable result without depending on
    real data.
    """
    bas = [(x + largeur * i / pas, y) for i in range(pas)]
    droite = [(x + largeur, y + hauteur * i / pas) for i in range(pas)]
    haut = [(x + largeur - largeur * i / pas, y + hauteur) for i in range(pas)]
    gauche = [(x, y + hauteur - hauteur * i / pas) for i in range(pas)]
    anneau = bas + droite + haut + gauche
    anneau.append(anneau[0])
    return {"type": "Polygon", "coordinates": [[list(p) for p in anneau]]}


def test_rounding_brings_back_to_five_decimals():
    geometrie = {"type": "Polygon", "coordinates": [[
        [1.123456789, 2.987654321], [3.0, 2.0], [3.0, 4.0], [1.123456789, 2.987654321],
    ]]}

    arrondie = round_coordinates(geometrie)

    assert arrondie["coordinates"][0][0] == [1.12346, 2.98765]


def test_the_tolerance_is_capped_by_the_footprint_size():
    """A 0.005° "spot" footprint must not be given a tolerance of 0.01."""
    minuscule = _rectangle(35.51, 33.88, 0.005, 0.0035)

    tolerance = effective_tolerance(minuscule, DEFAULT_TOLERANCE)

    diagonale = math.hypot(0.005, 0.0035)
    assert tolerance == pytest.approx(diagonale / SIZE_DIVISOR)
    assert tolerance < DEFAULT_TOLERANCE


def test_a_large_footprint_gets_the_full_tolerance():
    vaste = _rectangle(0.0, 0.0, 10.0, 10.0)

    assert effective_tolerance(vaste, DEFAULT_TOLERANCE) == DEFAULT_TOLERANCE


def test_simplification_removes_collinear_vertices():
    dense = _rectangle(0.0, 0.0, 10.0, 10.0, pas=20)
    sommets_avant = len(dense["coordinates"][0])

    simplifiee = simplify_geometry(dense)

    assert len(simplifiee["coordinates"][0]) < sommets_avant


def test_simplification_preserves_the_area_of_small_footprints():
    """The case that motivates the adaptive tolerance: without it, we dropped to 24 %."""
    minuscule = _rectangle(35.51, 33.88, 0.005, 0.0035, pas=6)

    simplifiee = simplify_geometry(minuscule)

    assert area_ratio(minuscule, simplifiee) > 0.80


def test_simplification_never_empties_a_geometry(monkeypatch):
    """The safety net against degeneration, actually exercised.

    With `preserve_topology=True`, GEOS never produces an empty or invalid result on
    sound input — even a tiny "spot" footprint or an extremely thin ring survives
    intact (verified empirically: no combination of size and tolerance is enough to
    make it degenerate). So the net only protects against a pathology that neither the
    original geometry nor the tolerance can provoke here; we simulate it for real, by
    forcing GEOS to return an empty geometry, as it could on genuinely twisted field
    data.
    """
    geometrie = _rectangle(35.51, 33.88, 0.005, 0.0035, pas=6)

    def simplification_degeneree(self, tolerance, preserve_topology=True):
        return Polygon()

    monkeypatch.setattr(BaseGeometry, "simplify", simplification_degeneree)

    simplifiee = simplify_geometry(geometrie)

    assert simplifiee["coordinates"][0]
    assert area_ratio(geometrie, simplifiee) == pytest.approx(1.0)


def test_the_fallback_rounds_the_original_when_the_rounded_simplification_degenerates(
    monkeypatch,
):
    """Validity has to be checked on the rounded result, not before.

    The real mechanism behind `VN:s59g`: Douglas-Peucker (with
    `preserve_topology=True`) returns a valid result here, with non-zero area, but two
    of its vertices are so close (less than 1e-5°) that rounding to 5 decimals
    conflates them, collapsing the ring onto a single point. Checking `simplifiee`
    (before rounding) would let it through as-is; it is
    `round_coordinates(mapping(simplifiee))` that has to be invalidated to trigger the
    fallback to the rounded original — itself unharmed, since it shares no vertex with
    the simplified geometry.
    """
    original = _rectangle(0.0, 0.0, 10.0, 10.0, pas=4)

    degenere_a_l_arrondi = Polygon(
        [(0.0, 0.0), (0.000002, 0.0), (0.000001, 0.000002), (0.0, 0.0)]
    )
    assert degenere_a_l_arrondi.is_valid and degenere_a_l_arrondi.area > 0
    # Sanity check: it really is the rounding, and not `degenere_a_l_arrondi` itself,
    # that breaks — otherwise this test would prove nothing about the new ordering.
    arrondie = shape(round_coordinates(mapping(degenere_a_l_arrondi)))
    assert arrondie.is_empty or not arrondie.is_valid or arrondie.area == 0

    def simplification_qui_degenere_a_l_arrondi(self, tolerance, preserve_topology=True):
        return degenere_a_l_arrondi

    monkeypatch.setattr(BaseGeometry, "simplify", simplification_qui_degenere_a_l_arrondi)

    resultat = simplify_geometry(original)

    assert shape(resultat).is_valid
    assert resultat == round_coordinates(original)


def test_the_hausdorff_distance_stays_under_the_effective_tolerance():
    dense = _rectangle(0.0, 0.0, 10.0, 10.0, pas=20)

    simplifiee = simplify_geometry(dense)

    assert hausdorff(dense, simplifiee) <= DEFAULT_TOLERANCE * 2


def test_a_multipolygon_is_simplified_part_by_part():
    # A Polygon's `["coordinates"]` is already a list of rings (here just one, the
    # outer): that is the shape expected for a MultiPolygon element. Indexing `[0]`
    # would give the bare ring, without that nesting level, and `shape()` would no
    # longer be able to read it.
    multi = {"type": "MultiPolygon", "coordinates": [
        _rectangle(0.0, 0.0, 5.0, 5.0, pas=10)["coordinates"],
        _rectangle(20.0, 20.0, 5.0, 5.0, pas=10)["coordinates"],
    ]}

    simplifiee = simplify_geometry(multi)

    assert simplifiee["type"] == "MultiPolygon"
    assert len(simplifiee["coordinates"]) == 2


def _multi(*rectangles: dict) -> dict:
    return {"type": "MultiPolygon",
            "coordinates": [r["coordinates"] for r in rectangles]}


def test_a_polygon_gives_a_single_bbox_equal_to_its_bounds():
    geometrie = _rectangle(2.0, 48.0, 3.0, 1.0)

    assert part_bboxes(geometrie) == [(2.0, 48.0, 5.0, 49.0)]


def test_parts_on_either_side_of_the_antimeridian_keep_their_bboxes():
    """The Russian case: a national footprint straddling ±180° has -180…180 as its
    overall bbox, which covers the whole northern hemisphere — a click in London
    downloaded Russia's 8.3 MB for nothing. Per part, no box crosses the meridian and
    the prefilter discriminates again."""
    geometrie = _multi(
        _rectangle(170.0, 55.0, 9.0, 10.0),
        _rectangle(-179.0, 55.0, 9.0, 10.0),
    )

    boites = part_bboxes(geometrie)

    assert len(boites) == 2
    assert all(max_lon - min_lon < 30 for min_lon, _, max_lon, _ in boites)


def test_a_distant_island_keeps_its_own_bbox():
    """The Norwegian case: Bouvet, at -54° of latitude, stretched the country's bbox
    across 135° of latitude. The island must stay in its own box."""
    continent = [_rectangle(5.0 + i, 58.0, 0.8, 0.8) for i in range(5)]
    bouvet = _rectangle(3.0, -54.5, 0.5, 0.5)

    boites = part_bboxes(_multi(*continent, bouvet))

    assert (3.0, -54.5, 3.5, -54.0) in boites
    assert all(max_lat - min_lat < 30 for _, min_lat, _, max_lat in boites)


def test_the_number_of_boxes_is_capped_and_everything_stays_covered():
    """A national outline has hundreds of islands: one box per island would blow up the
    index. At the cap, every part must stay covered by at least one box."""
    parties = [_rectangle(float(i * 7), float((i * 13) % 50), 1.0, 1.0) for i in range(40)]

    boites = part_bboxes(_multi(*parties), max_boxes=4)

    assert len(boites) <= 4
    for partie in parties:
        min_lon, min_lat, max_lon, max_lat = shape(partie).bounds
        assert any(
            b[0] <= min_lon and b[1] <= min_lat and b[2] >= max_lon and b[3] >= max_lat
            for b in boites
        )
