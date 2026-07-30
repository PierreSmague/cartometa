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
