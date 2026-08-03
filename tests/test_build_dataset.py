import json
from pathlib import Path

import pytest

from cartometa.build.dataset import build_dataset, discover_countries


def _carre(x: float, y: float, cote: float) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [x, y], [x + cote, y], [x + cote, y + cote], [x, y + cote], [x, y],
    ]]}


def _meta(meta_id: str) -> dict:
    return {
        "id": meta_id, "tier": "regional", "title": f"titre {meta_id}",
        "description": "description", "category": "autre",
        "image": f"input/{meta_id}.webp",
        "source_url": f"https://www.plonkit.net/x#{meta_id}",
    }


def _ecrire_pays(data_dir: Path, pays: str, entrees: list[tuple[str, str, float]]) -> None:
    (data_dir / "metas").mkdir(parents=True, exist_ok=True)
    (data_dir / "geo").mkdir(parents=True, exist_ok=True)
    (data_dir / "metas" / f"{pays}.json").write_text(
        json.dumps([_meta(i) for i, _, _ in entrees]), "utf-8"
    )
    (data_dir / "geo" / f"{pays}.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {"id": i, "status": statut, "pieces": []},
             "geometry": _carre(0.0, 0.0, cote) if statut == "validé" else None}
            for i, statut, cote in entrees
        ],
    }), "utf-8")


@pytest.fixture
def data_dir(tmp_path):
    _ecrire_pays(tmp_path / "data", "PL", [("pl1", "validé", 3.0), ("pl2", "rejeté", 1.0)])
    _ecrire_pays(tmp_path / "data", "BW", [("bw1", "validé", 2.0)])
    return tmp_path / "data"


def test_seules_les_metas_validees_entrent_dans_le_jeu(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    assert {entree[0] for entree in jeu.index} == {"pl1", "bw1"}


def test_l_index_est_trie_par_surface_croissante(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    assert [entree[0] for entree in jeu.index] == ["bw1", "pl1"]


def test_chaque_meta_est_dans_le_fichier_de_son_pays_et_nulle_part_ailleurs(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    assert set(jeu.countries["PL"]["geometries"]) == {"pl1"}
    assert set(jeu.countries["BW"]["geometries"]) == {"bw1"}


def test_l_index_et_les_fichiers_pays_portent_exactement_les_memes_identifiants(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    depuis_index = {entree[0] for entree in jeu.index}
    depuis_pays = {i for pays in jeu.countries.values() for i in pays["geometries"]}
    assert depuis_index == depuis_pays


def test_l_index_porte_la_bbox_et_le_pays(data_dir):
    jeu = build_dataset(data_dir, ["BW"])

    identifiant, pays, min_lon, min_lat, max_lon, max_lat, surface = jeu.index[0]
    assert (identifiant, pays) == ("bw1", "BW")
    assert (min_lon, min_lat, max_lon, max_lat) == (0.0, 0.0, 2.0, 2.0)
    assert surface == pytest.approx(4.0)


def test_la_meta_porte_le_chemin_de_son_image_source(data_dir):
    jeu = build_dataset(data_dir, ["BW"])

    assert jeu.countries["BW"]["metas"]["bw1"]["image_source"] == "input/bw1.webp"


def test_un_pays_sans_meta_validee_est_absent_du_resultat(tmp_path):
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0)])
    (data_dir / "geo" / "BD.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []}), "utf-8"
    )

    jeu = build_dataset(data_dir, ["BD", "PL"])

    assert set(jeu.countries) == {"PL"}


def test_les_statuts_herites_sont_comptes_et_non_publies(tmp_path):
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "LG", [("lg1", "validé", 1.0)])
    chemin = data_dir / "geo" / "LG.geojson"
    geo = json.loads(chemin.read_text("utf-8"))
    geo["features"].append({
        "type": "Feature",
        "properties": {"id": "lg2", "status": "auto", "pieces": []},
        "geometry": _carre(5.0, 5.0, 1.0),
    })
    chemin.write_text(json.dumps(geo), "utf-8")
    (data_dir / "metas" / "LG.json").write_text(
        json.dumps([_meta("lg1"), _meta("lg2")]), "utf-8"
    )

    jeu = build_dataset(data_dir, ["LG"])

    assert jeu.legacy_statuses == 1
    assert set(jeu.countries["LG"]["geometries"]) == {"lg1"}


def test_geometries_presentes_mais_aucune_meta_leve(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "geo").mkdir(parents=True)
    (data_dir / "geo" / "ZZ.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "zz1", "status": "validé", "pieces": []},
                      "geometry": _carre(0.0, 0.0, 1.0)}],
    }), "utf-8")

    with pytest.raises(SystemExit, match=r"metas\.json"):
        build_dataset(data_dir, ["ZZ"])


def test_discover_countries_trie_et_met_en_majuscules(data_dir):
    assert discover_countries(data_dir) == ["BW", "PL"]


def _ecrire_meta_manuelle(data_dir: Path, pays: str, meta_id: str,
                          source_url: str = "") -> None:
    """Une méta saisie via la touche `N` du reviewer.

    Contrairement aux textes Plonk It, `data/manual/` est versionné : l'image
    d'un contributeur arrive dans le dépôt avec son tracé. Et son `source_url`
    est facultatif — ces métas sont souvent trouvées en explorant une carte,
    sans page d'origine à citer — d'où la chaîne vide par défaut, telle que
    `cartometa/review/manual.py` l'écrit.
    """
    manuel = data_dir / "manual" / pays
    (manuel / "images").mkdir(parents=True, exist_ok=True)
    (manuel / "metas.json").write_text(json.dumps([{
        "id": meta_id, "tier": "manual", "title": f"titre {meta_id}",
        "description": "description", "category": "autre", "origin": "manual",
        "image": f"data/manual/{pays}/images/{meta_id}.png",
        "source_url": source_url,
    }]), "utf-8")
    (data_dir / "geo").mkdir(parents=True, exist_ok=True)
    (data_dir / "geo" / f"{pays}.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": meta_id, "status": "validé",
                                     "pieces": []},
                      "geometry": _carre(0.0, 0.0, 1.0)}],
    }), "utf-8")


def test_une_meta_manuelle_est_publiee(tmp_path):
    """Couverture restaurée : les deux tests du chemin manuel vivaient dans
    `tests/test_export.py`, supprimé avec l'ancienne commande d'export sans
    que personne ne les reporte ici."""
    data_dir = tmp_path / "data"
    _ecrire_meta_manuelle(data_dir, "XX", "man-1a2b")

    jeu = build_dataset(data_dir, ["XX"])

    assert [entree[0] for entree in jeu.index] == ["man-1a2b"]
    meta = jeu.countries["XX"]["metas"]["man-1a2b"]
    assert meta["image_source"] == "data/manual/XX/images/man-1a2b.png"


def test_un_pays_sans_source_importee_mais_avec_des_metas_manuelles_reussit(tmp_path):
    """L'absence de `data/metas/<CC>.json` ne doit pas être fatale : la seule
    source manuelle suffit. Le dossier `metas/` n'est même pas créé ici."""
    data_dir = tmp_path / "data"
    _ecrire_meta_manuelle(data_dir, "YY", "man-only1")

    jeu = build_dataset(data_dir, ["YY"])

    assert not (data_dir / "metas").exists()
    assert [entree[0] for entree in jeu.index] == ["man-only1"]


def test_une_meta_manuelle_sans_source_traverse_le_build_avec_une_chaine_vide(tmp_path):
    """Le champ source est facultatif à la saisie et le reste ici : c'est le
    front qui doit s'abstenir d'afficher un lien « source » vide, pas le build
    qui doit inventer une URL. On vérifie donc que la chaîne vide arrive
    intacte jusqu'au fichier pays, sans exception ni valeur fabriquée."""
    data_dir = tmp_path / "data"
    _ecrire_meta_manuelle(data_dir, "ZZ", "man-nosrc", source_url="")

    jeu = build_dataset(data_dir, ["ZZ"])

    assert jeu.countries["ZZ"]["metas"]["man-nosrc"]["source_url"] == ""
