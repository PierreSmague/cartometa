import math

import pytest
from shapely.geometry import Point, mapping, shape

from cartometa.build.geometry import simplify_geometry
from cartometa.tagged.geometry import (
    corridor_geometry,
    geometry_to_pieces,
    mst_edges,
    zone_geometry,
)

# ~0.009° de longitude ≈ 1 km vers 50° N (facteur cos appliqué par la projection).
KM_LON = 1 / (111.320 * math.cos(math.radians(50.0)))
KM_LAT = 1 / 110.574


def _chain(n, step_km=2.0, lat=50.0, lng0=20.0):
    """n points alignés ouest→est, espacés de step_km."""
    return [(lat, lng0 + i * step_km * KM_LON) for i in range(n)]


def test_a_chain_of_points_becomes_one_ribbon():
    geom = corridor_geometry(_chain(10))
    assert geom.geom_type == "Polygon"
    # 18 km de long sur 500 m de large : l'aire est celle d'un ruban, pas d'une enveloppe.
    aire_km2 = geom.area * 110.574 * 111.320 * math.cos(math.radians(50.0))
    assert aire_km2 == pytest.approx(18 * 0.5, rel=0.15)


def test_two_far_apart_segments_become_two_ribbons():
    points = _chain(5) + _chain(5, lng0=21.0)  # ~40 km d'écart, > link_km
    geom = corridor_geometry(points)
    assert geom.geom_type == "MultiPolygon"
    assert len(geom.geoms) == 2


def test_an_isolated_point_becomes_a_disc():
    geom = corridor_geometry([(50.0, 20.0)])
    assert geom.geom_type == "Polygon"
    assert geom.contains(Point(20.0, 50.0))


def test_a_closed_loop_keeps_its_hole():
    # Une rocade : 72 points sur un cercle de 5 km de rayon, espacés d'environ
    # 436 m. Un MST est acyclique : il laisse toujours un vide entre les deux
    # extrémités du chemin qu'il trace. Ce vide ne se referme que si les buffers
    # des deux bouts (2 x buffer_m = 500 m ici) se rejoignent, donc l'espacement
    # entre points adjacents doit rester sous 2 x buffer_m pour que la boucle
    # se referme et que l'union des buffers forme un anneau — c'est l'union qui
    # ferme la boucle, pas l'arbre.
    centre_lat, centre_lng = 50.0, 20.0
    points = [
        (centre_lat + 5 * KM_LAT * math.sin(a), centre_lng + 5 * KM_LON * math.cos(a))
        for a in [i * 2 * math.pi / 72 for i in range(72)]
    ]
    geom = corridor_geometry(points)
    assert not geom.contains(Point(centre_lng, centre_lat))
    pieces = geometry_to_pieces(geom, simplify_deg=0.0005)
    assert any(piece.get("holes") for piece in pieces)


def test_mst_links_every_point():
    xy = [(0.0, 0.0), (1.0, 0.0), (0.5, 5.0)]
    edges = mst_edges(xy)
    assert len(edges) == 2
    assert {i for a, b, _ in edges for i in (a, b)} == {0, 1, 2}


def test_two_clusters_become_two_hulls():
    # Deux nuages de 3×3 points espacés de 15 km, à ~600 km l'un de l'autre.
    def _grid(lng0):
        return [
            (50.0 + i * 15 * KM_LAT, lng0 + j * 15 * KM_LON)
            for i in range(3) for j in range(3)
        ]
    geom = zone_geometry(_grid(20.0) + _grid(28.0))
    assert geom.geom_type == "MultiPolygon"
    assert len(geom.geoms) == 2


def test_a_hull_covers_all_its_points_with_margin():
    points = [(50.0, 20.0), (50.3, 20.5), (50.1, 20.9), (49.8, 20.4)]
    geom = zone_geometry(points)
    for lat, lng in points:
        # Le buffer de 10 km met chaque point nettement à l'intérieur.
        assert geom.contains(Point(lng, lat).buffer(0.01))


def test_a_pair_of_points_becomes_a_capsule():
    geom = zone_geometry([(50.0, 20.0), (50.0, 20.1)])
    assert geom.geom_type == "Polygon"
    assert geom.contains(Point(20.05, 50.0))


def test_pieces_rings_are_open_and_capped():
    geom = corridor_geometry(_chain(50))
    pieces = geometry_to_pieces(geom, simplify_deg=0.0005)
    for piece in pieces:
        assert piece["kind"] == "polygon"
        assert piece["ring"][0] != piece["ring"][-1]
        assert len(piece["ring"]) <= 20_000


def test_a_corridor_survives_the_build_simplification():
    # Régression : effective_tolerance borne la tolérance par la largeur moyenne,
    # un ruban de 500 m ne doit pas être pulvérisé par le défaut de 0.01°.
    geom = corridor_geometry(_chain(30))
    simplifiee = shape(simplify_geometry(mapping(geom)))
    assert simplifiee.area == pytest.approx(geom.area, rel=0.25)


def test_an_empty_cloud_is_refused():
    with pytest.raises(ValueError):
        corridor_geometry([])
    with pytest.raises(ValueError):
        zone_geometry([])
