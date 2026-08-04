import json

import pytest

from cartometa.models import STATUS_REJECTED, STATUS_TRACED
from cartometa.review.store import (
    CountryPaths,
    UnknownMetaError,
    build_queue,
    clear_decision,
    load_geo,
    load_metas,
    set_decision,
)

CARRE = {"type": "Polygon",
         "coordinates": [[[2.0, 48.0], [3.0, 48.0], [3.0, 49.0], [2.0, 49.0], [2.0, 48.0]]]}


def _meta(meta_id, **extra):
    base = {
        "id": meta_id, "country": "PL", "tier": "regional", "title": f"titre {meta_id}",
        "description": "description", "category": "autre",
        "source_url": f"https://www.plonkit.net/poland#{meta_id}",
        "extracted_at": "2026-07-30T00:00:00+00:00", "image": f"input/{meta_id}.webp",
    }
    base.update(extra)
    return base


@pytest.fixture
def paths(tmp_path):
    p = CountryPaths(tmp_path / "data", "PL")
    p.imported_metas.parent.mkdir(parents=True)
    p.imported_metas.write_text(json.dumps([_meta("aaaa"), _meta("bbbb")]), "utf-8")
    p.manual_metas.parent.mkdir(parents=True)
    p.manual_metas.write_text(json.dumps([
        _meta("man-1a2b", tier="manual", origin="manual",
              image="data/manual/PL/images/man-1a2b.png"),
    ]), "utf-8")
    return p


def test_la_file_fusionne_les_deux_sources(paths):
    queue = build_queue(paths)

    assert [item["id"] for item in queue["items"]] == ["aaaa", "bbbb", "man-1a2b"]


def test_la_file_expose_le_chemin_d_image_en_url(paths):
    queue = build_queue(paths)

    images = {item["id"]: item["image"] for item in queue["items"]}
    assert images["aaaa"] == "/input/aaaa.webp"
    assert images["man-1a2b"] == "/data/manual/PL/images/man-1a2b.png"


def test_la_file_ignore_par_defaut_les_metas_deja_traitees(paths):
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, [{"kind": "rect", "bounds": [2, 48, 3, 49]}])

    queue = build_queue(paths)

    assert [item["id"] for item in queue["items"]] == ["bbbb", "man-1a2b"]
    assert queue["done"] == 1
    assert queue["total"] == 3


def test_une_meta_rejetee_ne_revient_pas_dans_la_file(paths):
    set_decision(paths, "bbbb", STATUS_REJECTED, None, [])

    assert "bbbb" not in {item["id"] for item in build_queue(paths)["items"]}


def test_include_all_rouvre_tout_avec_les_morceaux(paths):
    morceaux = [{"kind": "admin1", "code": "POL-1"}]
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, morceaux)

    queue = build_queue(paths, include_all=True)

    rouverte = next(item for item in queue["items"] if item["id"] == "aaaa")
    assert rouverte["status"] == STATUS_TRACED
    assert rouverte["pieces"] == morceaux


def test_done_compte_les_decidees_absentes_de_la_file_dans_les_deux_modes(paths):
    """`done` doit rester cohérent avec `done + len(items) == total` :

    par défaut la méta décidée est exclue de la file (`done` vaut 1) ; sous
    `include_all` elle y est réintégrée (`done` retombe à 0), sans quoi la
    formule de progression du client dépasserait le total (`67/37` observé
    sur un pays de 37 métas / 30 décidées).
    """
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, [{"kind": "country"}])

    defaut = build_queue(paths)
    assert defaut["done"] == 1
    assert defaut["done"] + len(defaut["items"]) == defaut["total"]

    tout = build_queue(paths, include_all=True)
    assert tout["done"] == 0
    assert tout["done"] + len(tout["items"]) == tout["total"]


def test_une_meta_jamais_traitee_arrive_sans_statut_ni_morceau(paths):
    item = build_queue(paths)["items"][0]

    assert item["status"] is None
    assert item["pieces"] == []


def test_la_decision_est_relue_a_l_identique(paths):
    morceaux = [{"kind": "rect", "bounds": [2.0, 48.0, 3.0, 49.0]}]
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, morceaux)

    record = load_geo(paths)["aaaa"]

    assert record.geometry == CARRE
    assert record.pieces == morceaux
    assert record.status == STATUS_TRACED


def test_le_geojson_est_ecrit_compact(paths):
    """L'indentation coûtait un facteur 4 mesuré sur les vrais fichiers :
    RU.geojson pesait 90 Mo (4,1 millions de lignes) contre 25 Mo compact.
    Chaque coordonnée sur sa propre ligne, versionnée, à chaque re-trace."""
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, [{"kind": "country"}])

    texte = paths.geo.read_text("utf-8")

    assert "\n" not in texte.strip()


def test_les_coordonnees_sont_arrondies_a_cinq_decimales(paths):
    """Cinq décimales ≈ 1 m au sol : largement assez pour une emprise de méta,
    et ~10 % de moins que les quinze décimales d'un float64 sérialisé. Les
    `pieces` sont arrondies aussi — elles ne portent que des coordonnées."""
    fin = {"type": "Polygon", "coordinates": [[
        [2.123456789, 48.987654321], [3.111111111, 48.0],
        [3.0, 49.222222222], [2.123456789, 48.987654321],
    ]]}
    morceaux = [{"kind": "polygon", "ring": [[2.123456789, 48.987654321]]}]

    set_decision(paths, "aaaa", STATUS_TRACED, fin, morceaux)

    record = load_geo(paths)["aaaa"]
    assert record.geometry["coordinates"][0][0] == [2.12346, 48.98765]
    assert record.pieces[0]["ring"] == [[2.12346, 48.98765]]


# Anneau valide dont l'arrondi à 5 décimales est invalide : le sommet
# (0.4, 0.399996) rejoint (0.4, 0.4) déjà présent, et l'anneau passe alors
# deux fois par le même point. C'est arrivé sur les vraies données : 8
# emprises sur 3617 ont dégénéré ainsi à la première migration.
ANNEAU_FRAGILE = [
    [0.0, 0.0], [0.8, 0.0], [0.4, 0.399996], [0.8, 0.8], [0.0, 0.8], [0.4, 0.4],
    [0.0, 0.0],
]


def test_une_geometrie_que_l_arrondi_invaliderait_garde_sa_precision(paths):
    from shapely.geometry import shape

    fragile = {"type": "Polygon", "coordinates": [ANNEAU_FRAGILE]}
    # Préconditions : valide telle quelle, invalide une fois arrondie —
    # sans quoi ce test ne prouverait rien sur le repli.
    assert shape(fragile).is_valid
    arrondie = {"type": "Polygon", "coordinates": [
        [[round(x, 5), round(y, 5)] for x, y in ANNEAU_FRAGILE]
    ]}
    assert not shape(arrondie).is_valid

    set_decision(paths, "aaaa", STATUS_TRACED, fragile, [{"kind": "country"}])

    record = load_geo(paths)["aaaa"]
    assert shape(record.geometry).is_valid
    assert record.geometry["coordinates"] == fragile["coordinates"]


def test_un_anneau_de_piece_que_l_arrondi_invaliderait_garde_sa_precision(paths):
    """Les `pieces` servent à rouvrir une méta : `resolve_pieces` reconstruit
    des polygones depuis leurs anneaux, et un anneau devenu invalide à
    l'arrondi casserait cette réouverture."""
    morceaux = [{"kind": "polygon", "ring": ANNEAU_FRAGILE}]

    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, morceaux)

    record = load_geo(paths)["aaaa"]
    assert record.pieces[0]["ring"] == ANNEAU_FRAGILE


def test_annuler_retire_la_meta_du_fichier(paths):
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, [{"kind": "country"}])

    clear_decision(paths, "aaaa")

    assert "aaaa" not in load_geo(paths)


def test_annuler_une_meta_sans_decision_leve(paths):
    with pytest.raises(UnknownMetaError):
        clear_decision(paths, "aaaa")


def test_decider_sur_une_meta_inconnue_leve(paths):
    with pytest.raises(UnknownMetaError):
        set_decision(paths, "zzzz", STATUS_TRACED, CARRE, [{"kind": "country"}])


def test_statut_inconnu_refuse(paths):
    with pytest.raises(ValueError):
        set_decision(paths, "aaaa", "corrigé", CARRE, [{"kind": "country"}])


def test_pays_sans_fichier_importe(tmp_path):
    """Un pays peut n'avoir que des metas manuelles."""
    paths = CountryPaths(tmp_path / "data", "XX")
    paths.manual_metas.parent.mkdir(parents=True)
    paths.manual_metas.write_text(json.dumps([_meta("man-abcd", country="XX")]), "utf-8")

    assert [m["id"] for m in load_metas(paths)] == ["man-abcd"]


def test_pays_sans_aucune_source(tmp_path):
    assert load_metas(CountryPaths(tmp_path / "data", "XX")) == []
