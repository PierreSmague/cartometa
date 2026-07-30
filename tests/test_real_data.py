import json
from pathlib import Path

import pytest
from shapely.geometry import shape

pytestmark = pytest.mark.real_data

GEO_DIR = Path("data/geo")
STATUTS = {"validé", "rejeté"}


def _fichiers():
    fichiers = sorted(GEO_DIR.glob("*.geojson"))
    if not fichiers:
        pytest.skip("aucune géométrie : lancer cartometa-review")
    return fichiers


def test_toute_geometrie_enregistree_est_valide():
    for chemin in _fichiers():
        for feature in json.loads(chemin.read_text("utf-8"))["features"]:
            if feature["geometry"] is None:
                continue
            geom = shape(feature["geometry"])
            assert geom.is_valid, f"{chemin.name}: {feature['properties']['id']}"
            assert not geom.is_empty


def test_seuls_les_deux_statuts_prevus_existent():
    for chemin in _fichiers():
        for feature in json.loads(chemin.read_text("utf-8"))["features"]:
            statut = feature["properties"]["status"]
            assert statut in STATUTS, f"{chemin.name}: statut inattendu {statut!r}"


def test_une_meta_tracee_a_toujours_une_geometrie_et_ses_morceaux():
    for chemin in _fichiers():
        for feature in json.loads(chemin.read_text("utf-8"))["features"]:
            props = feature["properties"]
            if props["status"] != "validé":
                continue
            assert feature["geometry"] is not None, f"{chemin.name}: {props['id']}"
            assert props["pieces"], f"{chemin.name}: {props['id']} sans morceau"


def test_une_meta_rejetee_ne_porte_aucune_geometrie():
    for chemin in _fichiers():
        for feature in json.loads(chemin.read_text("utf-8"))["features"]:
            props = feature["properties"]
            if props["status"] == "rejeté":
                assert feature["geometry"] is None, f"{chemin.name}: {props['id']}"
