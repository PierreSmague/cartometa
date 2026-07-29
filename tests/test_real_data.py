import json
from pathlib import Path
import pytest
from shapely.geometry import shape, Point

pytestmark = pytest.mark.real_data
GEO = Path("data/geo/PL.geojson")
METAS = Path("data/metas/PL.json")


def _skip_unless_built():
    if not GEO.exists() or not METAS.exists():
        pytest.skip("lancer d'abord cartometa-extract puis cartometa-geo")


def test_every_geometry_is_valid():
    """Toute géométrie produite doit être valide.

    NOTE (correction) : une méta peut légitimement n'avoir aucune géométrie
    (`"geometry": null`), par exemple une méta `spot` sans lien Maps ou une
    méta `regional` sans encart détectable — c'est le comportement documenté
    et voulu (avertissement explicite, pas de géométrie fantaisiste). Le test
    tel qu'initialement écrit appelait `shape(None)` sans condition, ce qui
    lève `AttributeError` dès qu'une seule méta est dans ce cas (ce qui arrive
    en pratique : 4/35 sur la Pologne). On ne teste donc que les géométries
    réellement produites.
    """
    _skip_unless_built()
    data = json.loads(GEO.read_text("utf-8"))
    for feature in data["features"]:
        if feature["geometry"] is None:
            continue
        geom = shape(feature["geometry"])
        assert geom.is_valid, f"géométrie invalide: {feature['properties']['id']}"
        assert not geom.is_empty


def test_country_tier_covers_warsaw():
    _skip_unless_built()
    data = json.loads(GEO.read_text("utf-8"))
    metas = {m["id"]: m for m in json.loads(METAS.read_text("utf-8"))}
    warsaw = Point(21.0122, 52.2297)
    national = [f for f in data["features"] if metas[f["properties"]["id"]]["tier"] == "country"]
    assert national, "aucune méta nationale"
    assert all(shape(f["geometry"]).contains(warsaw) for f in national)


def test_no_geometry_covers_a_point_in_the_atlantic():
    """Même correction que ci-dessus : ignorer les features sans géométrie."""
    _skip_unless_built()
    data = json.loads(GEO.read_text("utf-8"))
    atlantic = Point(-30.0, 40.0)
    assert not any(
        shape(f["geometry"]).contains(atlantic)
        for f in data["features"]
        if f["geometry"] is not None
    )


def test_regional_geometries_contain_their_maps_point():
    """Mesure objective du taux de justesse — le chiffre qui décide de la suite."""
    _skip_unless_built()
    data = json.loads(GEO.read_text("utf-8"))
    metas = {m["id"]: m for m in json.loads(METAS.read_text("utf-8"))}
    checked, correct = 0, 0
    for feature in data["features"]:
        meta = metas[feature["properties"]["id"]]
        if meta["tier"] != "regional" or not meta["maps_latlon"]:
            continue
        checked += 1
        lat, lon = meta["maps_latlon"]
        if shape(feature["geometry"]).contains(Point(lon, lat)):
            correct += 1
    if checked == 0:
        pytest.skip("aucune méta regional avec coordonnées")
    print(f"\nTaux de justesse mesuré: {correct}/{checked} = {correct / checked:.0%}")
    assert correct / checked >= 0.7, f"sous la cible de 70 % : {correct}/{checked}"
