import json

import pytest
from shapely.geometry import shape

from cartometa.models import STATUS_REJECTED, STATUS_TRACED
from cartometa.review import server
from cartometa.review.pieces import PieceError
from cartometa.review.store import CountryPaths, load_geo


def _box(x0, y0, x1, y1):
    return {"type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


COUNTRIES = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"ISO_A2": "PL", "ISO_A2_EH": "PL", "NAME": "Poland"},
     "geometry": _box(14.0, 49.0, 24.0, 55.0)},
]}


@pytest.fixture
def paths(tmp_path):
    p = CountryPaths(tmp_path / "data", "PL")
    p.imported_metas.parent.mkdir(parents=True)
    p.imported_metas.write_text(json.dumps([{
        "id": "aaaa", "country": "PL", "tier": "regional", "title": "titre",
        "description": "description", "category": "autre", "image": None,
        "source_url": "https://www.plonkit.net/poland#aaaa",
        "extracted_at": "2026-07-30T00:00:00+00:00",
    }]), "utf-8")
    p.cache.mkdir(parents=True)
    (p.cache / "ne_10m_admin_0_countries.geojson").write_text(json.dumps(COUNTRIES), "utf-8")
    server.STATE["paths"] = p
    server.STATE["include_all"] = False
    return p


def test_la_decision_resout_les_morceaux_avant_d_ecrire(paths):
    server.apply_decision("aaaa", STATUS_TRACED, [{"kind": "rect", "bounds": [2, 48, 3, 49]}])

    record = load_geo(paths)["aaaa"]
    assert shape(record.geometry).bounds == (2.0, 48.0, 3.0, 49.0)
    assert record.status == STATUS_TRACED


def test_le_pays_entier_vient_de_natural_earth_pas_du_client(paths):
    """Le client n'envoie qu'un drapeau : la silhouette est relue cote serveur."""
    server.apply_decision("aaaa", STATUS_TRACED, [{"kind": "country"}])

    assert shape(load_geo(paths)["aaaa"].geometry).bounds == (14.0, 49.0, 24.0, 55.0)


def test_les_morceaux_sont_conserves_pour_rouvrir_la_meta(paths):
    morceaux = [{"kind": "rect", "bounds": [2, 48, 3, 49]}, {"kind": "country"}]

    server.apply_decision("aaaa", STATUS_TRACED, morceaux)

    assert load_geo(paths)["aaaa"].pieces == morceaux


def test_un_rejet_n_a_pas_besoin_de_morceaux(paths):
    server.apply_decision("aaaa", STATUS_REJECTED, [])

    record = load_geo(paths)["aaaa"]
    assert record.status == STATUS_REJECTED
    assert record.geometry is None


def test_valider_sans_morceau_est_refuse(paths):
    with pytest.raises(PieceError):
        server.apply_decision("aaaa", STATUS_TRACED, [])


def test_statut_inconnu_refuse(paths):
    with pytest.raises(ValueError):
        server.apply_decision("aaaa", "corrigé", [{"kind": "country"}])


def test_rien_n_est_ecrit_quand_un_morceau_est_invalide(paths):
    with pytest.raises(PieceError):
        server.apply_decision("aaaa", STATUS_TRACED, [{"kind": "rect", "bounds": [2, 48, 3, 999]}])

    assert load_geo(paths) == {}
