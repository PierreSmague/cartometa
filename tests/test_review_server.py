import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

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
    """Le client n'envoie qu'un drapeau : la silhouette est relue côté serveur."""
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


# --- Tests HTTP : au-dessus, `apply_decision` est testé en direct ; ici, on
# vérifie que le `Handler` qui l'appelle route, distingue les statuts, et ne
# répond jamais deux fois (ou zéro fois) pour une même requête. Le serveur
# n'écoute que sur la boucle locale (127.0.0.1, port 0 laissé au système) :
# aucune requête ne sort de la machine.


@pytest.fixture
def live_server(paths):
    httpd = HTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


def _get(base_url, route, timeout=5):
    with urllib.request.urlopen(base_url + route, timeout=timeout) as resp:
        return resp.status, resp.read()


def _post(base_url, route, payload=None, timeout=5):
    data = json.dumps(payload).encode("utf-8") if payload is not None else b""
    request = urllib.request.Request(base_url + route, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return resp.status, resp.read()


def test_post_decision_http_pieces_valides_ecrit_sur_le_disque(paths, live_server):
    status, body = _post(live_server, "/api/decision", {
        "id": "aaaa", "status": STATUS_TRACED, "pieces": [{"kind": "rect", "bounds": [2, 48, 3, 49]}],
    })

    assert status == 200
    assert json.loads(body) == {"ok": True}
    record = load_geo(paths)["aaaa"]
    assert shape(record.geometry).bounds == (2.0, 48.0, 3.0, 49.0)


def test_post_decision_http_meta_inconnue_donne_404(live_server):
    """Garde-fou contre l'ombrage des `except` : `UnknownMetaError` hérite de
    `ValueError`, un chaînage désordonné la ferait tomber en 400."""
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(live_server, "/api/decision", {
            "id": "zzzz", "status": STATUS_TRACED, "pieces": [{"kind": "country"}],
        })

    assert excinfo.value.code == 404
    body = json.loads(excinfo.value.read())
    assert body["ok"] is False


def test_post_decision_http_piece_invalide_donne_400_et_rien_n_est_ecrit(paths, live_server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(live_server, "/api/decision", {
            "id": "aaaa", "status": STATUS_TRACED,
            "pieces": [{"kind": "rect", "bounds": [2, 48, 3, 999]}],
        })

    assert excinfo.value.code == 400
    assert load_geo(paths) == {}


def test_post_decision_http_id_absent_donne_400_avec_le_champ_manquant(live_server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(live_server, "/api/decision", {"status": STATUS_TRACED, "pieces": [{"kind": "country"}]})

    assert excinfo.value.code == 400
    body = json.loads(excinfo.value.read())
    assert "id" in body["error"]


def test_post_decision_http_corps_json_invalide_donne_400(live_server):
    request = urllib.request.Request(
        live_server + "/api/decision", data=b"pas du json", method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)

    assert excinfo.value.code == 400


def test_post_route_inconnue_donne_404(live_server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(live_server, "/api/inexistante", {})

    assert excinfo.value.code == 404


def test_post_content_length_trop_grand_est_refuse_sans_lire_le_corps(live_server):
    request = urllib.request.Request(
        live_server + "/api/decision", data=b'{"id": "aaaa"}', method="POST"
    )
    request.add_header("Content-Length", "9999999999")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)

    assert excinfo.value.code == 400
    body = json.loads(excinfo.value.read())
    assert "volumineux" in body["error"]


def test_get_queue_http_reprend_les_metas_de_la_fixture(live_server):
    status, body = _get(live_server, "/api/queue")

    assert status == 200
    payload = json.loads(body)
    assert payload["country"] == "PL"
    assert [item["id"] for item in payload["items"]] == ["aaaa"]
    assert payload["items"][0]["title"] == "titre"


def test_get_category_http_est_un_passe_plat(live_server):
    status, body = _get(live_server, "/api/category?text=yellow%20bollards")

    assert status == 200
    assert json.loads(body) == {"category": "bollards"}


def test_get_fichier_sous_input_est_servi(paths, live_server, monkeypatch):
    racine = paths.data.parent
    (racine / "input").mkdir(parents=True, exist_ok=True)
    (racine / "input" / "photo.jpg").write_bytes(b"contenu-image")
    monkeypatch.setattr("os.getcwd", lambda: str(racine))

    status, body = _get(live_server, "/input/photo.jpg")

    assert status == 200
    assert body == b"contenu-image"


def test_get_pyproject_toml_hors_static_est_refuse(live_server):
    """Le reviewer avait confirmé que ce fichier était servi tel quel avant
    la restriction : ce test garde `ALLOWED_ROOT_PREFIXES` en place."""
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(live_server, "/pyproject.toml")

    assert excinfo.value.code == 404
