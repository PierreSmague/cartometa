import json
from pathlib import Path

import pytest
from PIL import Image

from cartometa.build.site import FILE_COUNT_LIMIT, FILE_COUNT_WARNING, build_site


def _carre(x: float, y: float, cote: float) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [x, y], [x + cote, y], [x + cote, y + cote], [x, y + cote], [x, y],
    ]]}


@pytest.fixture
def projet(tmp_path, monkeypatch):
    """Un projet minimal mais complet : données, images sources, gabarits.

    Les métas stockent le chemin de leur image relatif à la racine du projet
    (convention déjà en place dans `cartometa.extract` et `cartometa.review`),
    donc on se place dans `tmp_path` pour que cette racine soit celle du
    projet jetable et non celle du dépôt réel.
    """
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    (data / "metas").mkdir(parents=True)
    (data / "geo").mkdir(parents=True)
    images = tmp_path / "input"
    images.mkdir()
    Image.new("RGB", (1000, 500), (10, 20, 30)).save(images / "pl1.png")
    (data / "metas" / "PL.json").write_text(json.dumps([{
        "id": "pl1", "tier": "regional", "title": "titre", "description": "desc",
        "category": "autre", "image": "input/pl1.png",
        "source_url": "https://www.plonkit.net/poland#pl1",
    }]), "utf-8")
    (data / "geo" / "PL.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "pl1", "status": "validé", "pieces": []},
                      "geometry": _carre(14.0, 49.0, 5.0)}],
    }), "utf-8")

    viewer = tmp_path / "viewer"
    viewer.mkdir()
    (viewer / "index.html").write_text("<!doctype html><body>__CSS__ __JS__</body>", "utf-8")
    (viewer / "licence.html").write_text("<!doctype html><body>__CSS__</body>", "utf-8")
    (viewer / "style.css").write_text("body{margin:0}", "utf-8")
    (viewer / "app.js").write_text("console.log('x')", "utf-8")
    return tmp_path


def _manifeste(dist: Path) -> dict:
    return json.loads((dist / "data" / "manifest.json").read_text("utf-8"))


def test_le_manifeste_reference_des_fichiers_qui_existent(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    assert (dist / "data" / manifeste["index"]).exists()
    for entree in manifeste["countries"].values():
        assert (dist / "data" / entree["file"]).exists()


def test_toute_image_referencee_existe(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    base = manifeste["image_base"]
    for entree in manifeste["countries"].values():
        pays = json.loads((dist / "data" / entree["file"]).read_text("utf-8"))
        for meta in pays["metas"].values():
            assert (dist / base / meta["thumb"]).exists()
            assert (dist / base / meta["full"]).exists()


def test_la_meta_ne_porte_plus_le_chemin_source_apres_le_build(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    pays = json.loads(
        (dist / "data" / manifeste["countries"]["PL"]["file"]).read_text("utf-8")
    )
    assert "image_source" not in pays["metas"]["pl1"]


def test_image_base_est_dans_le_manifeste(projet):
    """La parade au plafond de fichiers : déplacer les images ne touche que ça."""
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert _manifeste(dist)["image_base"] == "img/"


def test_les_gabarits_recoivent_les_noms_empreintes(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    page = (dist / "index.html").read_text("utf-8")
    assert "__CSS__" not in page and "__JS__" not in page
    assert "style." in page and ".css" in page


def test_le_fichier_headers_est_produit_avec_les_deux_regimes(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    headers = (dist / "_headers").read_text("utf-8")
    assert "/data/manifest.json" in headers
    assert "no-cache" in headers
    assert "immutable" in headers


def test_deux_builds_identiques_donnent_les_memes_noms(projet):
    build_site(projet / "data", projet / "d1", projet / "viewer", ["PL"])
    build_site(projet / "data", projet / "d2", projet / "viewer", ["PL"])

    assert _manifeste(projet / "d1")["index"] == _manifeste(projet / "d2")["index"]


def test_skip_images_ne_produit_aucune_image(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"], skip_images=True)

    assert not (dist / "img").exists()


def test_le_resultat_compte_les_fichiers_produits(projet):
    resultat = build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    assert resultat["metas"] == 1
    assert resultat["files"] > 0
    assert FILE_COUNT_WARNING < FILE_COUNT_LIMIT


def test_une_image_source_absente_leve_avec_le_nom_de_la_meta(projet):
    (projet / "input" / "pl1.png").unlink()

    with pytest.raises(SystemExit, match="pl1"):
        build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])


def test_un_build_relance_ecrase_sans_laisser_de_residu(projet):
    dist = projet / "dist"
    build_site(projet / "data", dist, projet / "viewer", ["PL"])
    (dist / "data" / "vieux.json").write_text("{}", "utf-8")

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert not (dist / "data" / "vieux.json").exists()
