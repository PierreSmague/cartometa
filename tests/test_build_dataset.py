import json
import re
from pathlib import Path

import pytest

from cartometa.build.dataset import (
    SCOPE_NATIONAL,
    SCOPE_REGIONAL,
    build_dataset,
    discover_countries,
    scope_de,
)


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


def _ecrire_pays_pieces(
    data_dir: Path, pays: str, entrees: list[tuple[str, list[dict], float]]
) -> None:
    """Comme `_ecrire_pays`, mais en fixant les `pieces` de chaque emprise.

    `_ecrire_pays` les laisse vides, ce qui ne permet pas de distinguer une
    emprise nationale d'une régionale.
    """
    (data_dir / "metas").mkdir(parents=True, exist_ok=True)
    (data_dir / "geo").mkdir(parents=True, exist_ok=True)
    (data_dir / "metas" / f"{pays}.json").write_text(
        json.dumps([_meta(i) for i, _, _ in entrees]), "utf-8"
    )
    (data_dir / "geo" / f"{pays}.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {"id": i, "status": "validé", "pieces": pieces},
             "geometry": _carre(0.0, 0.0, cote)}
            for i, pieces, cote in entrees
        ],
    }), "utf-8")


@pytest.mark.parametrize("pieces,attendu", [
    ([{"kind": "country"}], "national"),
    ([{"kind": "country"}, {"kind": "country"}], "national"),
    ([{"kind": "polygon"}], "regional"),
    ([{"kind": "rect"}], "regional"),
    ([{"kind": "admin1"}], "regional"),
    ([{"kind": "clip"}, {"kind": "polygon"}], "regional"),
    # Un pays rogné n'est plus le pays entier : c'est ce que l'égalité
    # stricte capture et qu'un `"country" in kinds` manquerait.
    ([{"kind": "country"}, {"kind": "clip"}], "regional"),
    # Aucune emprise publiée n'a de pieces vides ; le repli garantit
    # qu'une telle emprise resterait visible sous « All ».
    ([], "regional"),
])
def test_la_portee_se_deduit_du_trace(pieces, attendu):
    assert scope_de(pieces) == attendu


def test_la_portee_est_publiee_pour_chaque_meta(tmp_path):
    """Sans ce champ dans la charge utile, le site n'a rien à filtrer."""
    _ecrire_pays_pieces(tmp_path / "data", "PL", [
        ("pl1", [{"kind": "country"}], 3.0),
        ("pl2", [{"kind": "polygon"}], 1.0),
    ])

    jeu = build_dataset(tmp_path / "data", ["PL"])

    metas = jeu.countries["PL"]["metas"]
    assert metas["pl1"]["scope"] == "national"
    assert metas["pl2"]["scope"] == "regional"


def test_les_valeurs_de_portee_du_front_correspondent_a_celles_du_build():
    """Contrat entre deux langages, donc invisible au compilateur comme au
    relecteur d'un seul fichier.

    Le build écrit `scope` dans la charge utile, le gabarit déclare la portée de
    chaque section repliable en `data-portee`, et `app.js` répartit les métas en
    comparant les deux. Renommer un côté sans l'autre ne casse rien de bruyant :
    les deux sections se masquent simplement comme si le point n'était couvert
    par aucune méta, sans le moindre message.

    L'égalité, et non une inclusion : une valeur de portée qui n'aurait pas sa
    section n'afficherait nulle part les métas qui la portent, et ce test est le
    seul endroit du projet où les deux listes se rencontrent.
    """
    html = (Path(__file__).resolve().parents[1] / "viewer" / "index.html").read_text("utf-8")

    valeurs = set(re.findall(r'data-portee="([^"]*)"', html))

    assert valeurs == {SCOPE_REGIONAL, SCOPE_NATIONAL}


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

    assert set(jeu.countries["PL"]["metas"]) == {"pl1"}
    assert set(jeu.countries["BW"]["metas"]) == {"bw1"}


def test_l_index_et_les_fichiers_pays_portent_exactement_les_memes_identifiants(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    depuis_index = {entree[0] for entree in jeu.index}
    depuis_pays = {i for pays in jeu.countries.values() for i in pays["metas"]}
    assert depuis_index == depuis_pays


def test_chaque_meta_reference_une_geometrie_publiee(data_dir):
    """Le contrat de la dédup : `geom` doit toujours pointer vers une entrée
    existante de `geometries`, sinon le front n'a rien à dessiner."""
    jeu = build_dataset(data_dir, ["PL", "BW"])

    for pays in jeu.countries.values():
        for meta in pays["metas"].values():
            assert meta["geom"] in pays["geometries"]


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
    assert set(jeu.countries["LG"]["metas"]) == {"lg1"}


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


def test_une_emprise_aux_parties_eloignees_donne_plusieurs_lignes_d_index(tmp_path):
    """Le préfiltre du viewer travaille sur les bbox de l'index : une seule
    bbox pour une emprise à cheval sur l'antiméridien couvre la planète et ne
    filtre plus rien. Chaque groupe de parties porte sa propre ligne — même
    id, même surface, bbox distincte — et le viewer déduplique les ids."""
    data_dir = tmp_path / "data"
    (data_dir / "metas").mkdir(parents=True)
    (data_dir / "geo").mkdir(parents=True)
    (data_dir / "metas" / "RU.json").write_text(json.dumps([_meta("ru1")]), "utf-8")
    (data_dir / "geo" / "RU.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "ru1", "status": "validé", "pieces": []},
                      "geometry": {"type": "MultiPolygon", "coordinates": [
                          _carre(170.0, 55.0, 9.0)["coordinates"],
                          _carre(-179.0, 55.0, 9.0)["coordinates"],
                      ]}}],
    }), "utf-8")

    jeu = build_dataset(data_dir, ["RU"])

    lignes = [e for e in jeu.index if e[0] == "ru1"]
    assert len(lignes) == 2
    assert all(e[4] - e[2] < 30 for e in lignes)  # aucune bbox ne traverse ±180°
    assert len({tuple(e[2:6]) for e in lignes}) == 2
    assert len({e[6] for e in lignes}) == 1  # même surface : le tri reste stable


def test_deux_metas_de_meme_emprise_partagent_une_seule_geometrie(tmp_path):
    """76 % du répertoire data/ publié était de la géométrie byte-identique
    dupliquée (25,9 Mo sur 34,2 mesurés) : chaque méta portait sa propre copie
    de son emprise, et RU stockait 19 fois le même contour national de 330 Ko.
    Les géométries sont donc publiées une seule fois, indexées par empreinte
    de contenu, et chaque méta référence la sienne par `geom`."""
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 2.0), ("pl2", "validé", 2.0)])

    jeu = build_dataset(data_dir, ["PL"])

    pays = jeu.countries["PL"]
    assert len(pays["geometries"]) == 1
    empreintes = {pays["metas"][i]["geom"] for i in ("pl1", "pl2")}
    assert empreintes == set(pays["geometries"])


def test_deux_metas_d_emprises_differentes_ne_partagent_rien(tmp_path):
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 2.0), ("pl2", "validé", 3.0)])

    jeu = build_dataset(data_dir, ["PL"])

    pays = jeu.countries["PL"]
    assert len(pays["geometries"]) == 2
    assert pays["metas"]["pl1"]["geom"] != pays["metas"]["pl2"]["geom"]


def test_une_emprise_sans_texte_est_comptee_comme_orpheline(tmp_path):
    """Une géométrie tracée dont la méta a disparu ne doit pas s'évaporer en
    silence : le build doit la compter et la nommer, comme il le fait déjà
    pour les statuts hérités. C'est arrivé en vrai : `man-d338` (PH) a été
    ignorée sans un mot pendant que le build annonçait un succès."""
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0), ("pl2", "validé", 1.0)])
    (data_dir / "metas" / "PL.json").write_text(json.dumps([_meta("pl1")]), "utf-8")

    jeu = build_dataset(data_dir, ["PL"])

    assert jeu.orphans == [("PL", "pl2")]
    assert set(jeu.countries["PL"]["metas"]) == {"pl1"}


def test_une_emprise_manuelle_orpheline_fait_echouer_le_build(tmp_path):
    """`data/manual/` est versionné précisément parce que ces données sont
    irremplaçables : un tracé `man-*` sans texte est une perte de données,
    pas un simple décalage de régénération. Le build doit échouer dur."""
    data_dir = tmp_path / "data"
    _ecrire_meta_manuelle(data_dir, "XX", "man-1a2b")
    geo_path = data_dir / "geo" / "XX.geojson"
    geo = json.loads(geo_path.read_text("utf-8"))
    geo["features"].append({
        "type": "Feature",
        "properties": {"id": "man-perdu", "status": "validé", "pieces": []},
        "geometry": _carre(5.0, 5.0, 1.0),
    })
    geo_path.write_text(json.dumps(geo), "utf-8")

    with pytest.raises(SystemExit, match=r"man-perdu"):
        build_dataset(data_dir, ["XX"])


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
