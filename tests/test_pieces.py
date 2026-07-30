import json

import pytest

from cartometa.geo.reference import DATASET_NAME
from cartometa.review.pieces import PieceError, resolve_pieces


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


def test_rectangle_dont_les_coins_sont_donnes_a_l_envers(cache_dir):
    """Deux clics sur la carte peuvent arriver dans n'importe quel ordre."""
    geom = resolve_pieces([{"kind": "rect", "bounds": [3.0, 49.0, 2.0, 48.0]}], "PL", cache_dir)

    assert geom.bounds == (2.0, 48.0, 3.0, 49.0)


def test_pays_entier(cache_dir):
    geom = resolve_pieces([{"kind": "country"}], "PL", cache_dir)

    assert geom.bounds == (14.0, 49.0, 24.0, 55.0)


def test_region_admin1(cache_dir):
    geom = resolve_pieces([{"kind": "admin1", "code": "POL-1"}], "PL", cache_dir)

    assert geom.bounds == (20.0, 51.0, 22.0, 53.0)


def test_contour_libre_est_ferme_automatiquement(cache_dir):
    ring = [[2.0, 48.0], [3.0, 48.0], [3.0, 49.0]]

    geom = resolve_pieces([{"kind": "polygon", "ring": ring}], "PL", cache_dir)

    assert geom.is_valid
    assert geom.area == pytest.approx(0.5)


def test_deux_regions_adjacentes_fusionnent_en_un_polygone(cache_dir):
    geom = resolve_pieces([
        {"kind": "admin1", "code": "POL-1"},
        {"kind": "admin1", "code": "POL-2"},
    ], "PL", cache_dir)

    assert geom.bounds == (19.0, 49.0, 22.0, 53.0)


def test_morceaux_disjoints_donnent_un_multipolygone(cache_dir):
    geom = resolve_pieces([
        {"kind": "rect", "bounds": [2.0, 48.0, 3.0, 49.0]},
        {"kind": "rect", "bounds": [10.0, 48.0, 11.0, 49.0]},
    ], "PL", cache_dir)

    assert geom.geom_type == "MultiPolygon"
    assert len(geom.geoms) == 2


def test_contour_auto_intersectant_est_repare(cache_dir):
    """Un noeud papillon trace a la souris ne doit pas etre rejete."""
    ring = [[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0]]

    geom = resolve_pieces([{"kind": "polygon", "ring": ring}], "PL", cache_dir)

    assert geom.is_valid
    assert geom.area > 0.0


def test_liste_vide_refusee(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([], "PL", cache_dir)


def test_contour_de_deux_sommets_refuse(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "polygon", "ring": [[2.0, 48.0], [3.0, 48.0]]}], "PL", cache_dir)


def test_coordonnee_hors_bornes_refusee(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "rect", "bounds": [2.0, 48.0, 3.0, 95.0]}], "PL", cache_dir)


def test_coordonnee_non_numerique_refusee(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "rect", "bounds": [2.0, 48.0, "est", 49.0]}], "PL", cache_dir)


def test_rectangle_degenere_refuse(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "rect", "bounds": [2.0, 48.0, 2.0, 49.0]}], "PL", cache_dir)


def test_type_de_morceau_inconnu_refuse(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "cercle", "radius_km": 25}], "PL", cache_dir)


def test_code_de_region_inconnu_refuse(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "admin1", "code": "POL-99"}], "PL", cache_dir)


def test_pays_absent_de_natural_earth_refuse(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "country"}], "ZZ", cache_dir)


def test_contour_trop_long_refuse(cache_dir):
    ring = [[float(i) / 1000.0, 48.0 + float(i) / 1000.0] for i in range(2001)]

    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "polygon", "ring": ring}], "PL", cache_dir)
