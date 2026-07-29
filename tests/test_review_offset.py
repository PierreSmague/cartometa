import json

import pytest
from shapely.geometry import shape

from cartometa.review import server


def _square(x: float, y: float, size: float = 1.0) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y],
        ]],
    }


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    (tmp_path / "metas").mkdir()
    (tmp_path / "geo").mkdir()
    (tmp_path / "metas" / "XX.json").write_text(json.dumps([
        {"id": "reg", "tier": "regional", "title": "t", "description": "d",
         "category": "autre", "image": None, "source_url": "u"},
        {"id": "vide", "tier": "regional", "title": "t", "description": "d",
         "category": "autre", "image": None, "source_url": "u"},
        {"id": "pt", "tier": "spot", "title": "t", "description": "d",
         "category": "autre", "image": None, "source_url": "u"},
    ]), "utf-8")
    (tmp_path / "geo" / "XX.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"id": "reg", "confidence": 0.5, "warnings": [], "status": "auto"},
             "geometry": _square(10.0, 50.0)},
            {"type": "Feature", "properties": {"id": "vide", "confidence": 0.1, "warnings": [], "status": "auto"},
             "geometry": None},
            {"type": "Feature", "properties": {"id": "pt", "confidence": 0.9, "warnings": [], "status": "auto"},
             "geometry": _square(20.0, 50.0, 0.2)},
        ],
    }), "utf-8")
    monkeypatch.setitem(server.STATE, "data", tmp_path)
    monkeypatch.setitem(server.STATE, "country", "XX")
    return tmp_path


def _feature(data_dir, meta_id):
    geo = json.loads((data_dir / "geo" / "XX.geojson").read_text("utf-8"))
    return next(f for f in geo["features"] if f["properties"]["id"] == meta_id)


def test_decalage_translate_le_polygone_et_marque_corrige(data_dir):
    server.apply_decision("reg", "validé", None, [0.5, -0.25])

    feature = _feature(data_dir, "reg")
    assert feature["properties"]["status"] == "corrigé"
    bounds = shape(feature["geometry"]).bounds
    assert bounds == pytest.approx((10.5, 49.75, 11.5, 50.75))


def test_decalage_conserve_la_geometrie_d_origine_pour_l_annulation(data_dir):
    server.apply_decision("reg", "validé", None, [0.5, 0.0])
    server.apply_undo("reg")

    feature = _feature(data_dir, "reg")
    assert feature["properties"]["status"] == "auto"
    assert shape(feature["geometry"]).bounds == pytest.approx((10.0, 50.0, 11.0, 51.0))
    assert "geometry_before_correction" not in feature["properties"]


def test_un_second_decalage_ne_recouvre_pas_la_sauvegarde(data_dir):
    """Deux corrections successives : U doit rendre l'original, pas l'intermédiaire."""
    server.apply_decision("reg", "validé", None, [0.5, 0.0])
    server.apply_decision("reg", "validé", None, [0.5, 0.0])
    server.apply_undo("reg")

    assert shape(_feature(data_dir, "reg")["geometry"]).bounds == pytest.approx((10.0, 50.0, 11.0, 51.0))


def test_decalage_refuse_sans_geometrie(data_dir):
    with pytest.raises(ValueError, match="aucune géométrie"):
        server.apply_decision("vide", "validé", None, [0.1, 0.1])
    assert _feature(data_dir, "vide")["properties"]["status"] == "auto"


def test_decalage_nul_refuse(data_dir):
    with pytest.raises(ValueError, match="décalage nul"):
        server.apply_decision("reg", "validé", None, [0.0, 0.0])


@pytest.mark.parametrize("offset", [[99.0, 0.0], [0.0, -99.0]])
def test_decalage_hors_bornes_refuse(data_dir, offset):
    with pytest.raises(ValueError, match="trop grand"):
        server.apply_decision("reg", "validé", None, offset)
    assert _feature(data_dir, "reg")["properties"]["status"] == "auto"


@pytest.mark.parametrize("offset", ["0.5", [0.5], [0.5, "x"], [float("nan"), 0.0]])
def test_decalage_malforme_refuse(data_dir, offset):
    with pytest.raises(ValueError):
        server.apply_decision("reg", "validé", None, offset)


def test_rayon_et_decalage_sont_exclusifs(data_dir):
    with pytest.raises(ValueError, match="une seule à la fois"):
        server.apply_decision("pt", "validé", 30.0, [0.1, 0.1])


def test_decision_simple_inchangee(data_dir):
    """Sans décalage, le comportement historique reste identique."""
    server.apply_decision("reg", "rejeté", None)

    feature = _feature(data_dir, "reg")
    assert feature["properties"]["status"] == "rejeté"
    assert shape(feature["geometry"]).bounds == pytest.approx((10.0, 50.0, 11.0, 51.0))


RECTANGLE = {"type": "Polygon", "coordinates": [[
    [12.0, 40.0], [13.0, 40.0], [13.0, 41.0], [12.0, 41.0], [12.0, 40.0]]]}


def test_rectangle_manuel_sur_une_meta_sans_geometrie(data_dir):
    """Cas d'usage principal : le pipeline a échoué, l'humain trace la zone."""
    server.apply_decision("vide", "validé", None, None, RECTANGLE)

    feature = _feature(data_dir, "vide")
    assert feature["properties"]["status"] == "corrigé"
    assert shape(feature["geometry"]).bounds == pytest.approx((12.0, 40.0, 13.0, 41.0))


def test_annuler_un_rectangle_manuel_rend_l_absence_de_geometrie(data_dir):
    server.apply_decision("vide", "validé", None, None, RECTANGLE)
    server.apply_undo("vide")

    feature = _feature(data_dir, "vide")
    assert feature["properties"]["status"] == "auto"
    assert feature["geometry"] is None


def test_rectangle_manuel_remplace_une_geometrie_existante(data_dir):
    server.apply_decision("reg", "validé", None, None, RECTANGLE)

    assert shape(_feature(data_dir, "reg")["geometry"]).bounds == pytest.approx((12.0, 40.0, 13.0, 41.0))


@pytest.mark.parametrize("geometry", [
    {"type": "Point", "coordinates": [1.0, 2.0]},
    {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 1.0]]]},
    {"type": "Polygon", "coordinates": [[[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0], [0.0, 0.0]]]},
    {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 0.0], [0.0, 0.0]]]},
    {"type": "Polygon", "coordinates": [[[0.0, 0.0], [400.0, 0.0], [400.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]},
    "pas un objet",
])
def test_geometrie_manuelle_invalide_refusee(data_dir, geometry):
    """Nœud papillon, anneau trop court, surface nulle, hors bornes WGS84."""
    with pytest.raises(ValueError):
        server.apply_decision("vide", "validé", None, None, geometry)
    assert _feature(data_dir, "vide")["properties"]["status"] == "auto"


def test_rectangle_et_decalage_sont_exclusifs(data_dir):
    with pytest.raises(ValueError, match="mutuellement exclusives"):
        server.apply_decision("reg", "validé", None, [0.1, 0.1], RECTANGLE)
