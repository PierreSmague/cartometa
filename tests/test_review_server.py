import json
import socket
import sys
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


def test_the_decision_resolves_the_pieces_before_writing(paths):
    server.apply_decision("aaaa", STATUS_TRACED, [{"kind": "rect", "bounds": [2, 48, 3, 49]}])

    record = load_geo(paths)["aaaa"]
    assert shape(record.geometry).bounds == (2.0, 48.0, 3.0, 49.0)
    assert record.status == STATUS_TRACED


def test_the_whole_country_comes_from_natural_earth_not_from_the_client(paths):
    """The client only sends a flag: the silhouette is re-read server-side."""
    server.apply_decision("aaaa", STATUS_TRACED, [{"kind": "country"}])

    assert shape(load_geo(paths)["aaaa"].geometry).bounds == (14.0, 49.0, 24.0, 55.0)


def test_the_pieces_are_kept_so_the_meta_can_be_reopened(paths):
    morceaux = [{"kind": "rect", "bounds": [2, 48, 3, 49]}, {"kind": "country"}]

    server.apply_decision("aaaa", STATUS_TRACED, morceaux)

    assert load_geo(paths)["aaaa"].pieces == morceaux


def test_a_rejection_needs_no_pieces(paths):
    server.apply_decision("aaaa", STATUS_REJECTED, [])

    record = load_geo(paths)["aaaa"]
    assert record.status == STATUS_REJECTED
    assert record.geometry is None


def test_validating_without_a_piece_is_refused(paths):
    with pytest.raises(PieceError):
        server.apply_decision("aaaa", STATUS_TRACED, [])


def test_an_unknown_status_is_refused(paths):
    with pytest.raises(ValueError):
        server.apply_decision("aaaa", "corrigé", [{"kind": "country"}])


def test_nothing_is_written_when_a_piece_is_invalid(paths):
    with pytest.raises(PieceError):
        server.apply_decision("aaaa", STATUS_TRACED, [{"kind": "rect", "bounds": [2, 48, 3, 999]}])

    assert load_geo(paths) == {}


# --- HTTP tests: above, `apply_decision` is tested directly; here we check that the
# `Handler` calling it routes, tells the statuses apart, and never answers twice (or
# zero times) for one request. The server only listens on the loopback interface
# (127.0.0.1, port 0 left to the system): no request leaves the machine.


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


def test_post_decision_http_with_valid_pieces_writes_to_disk(paths, live_server):
    status, body = _post(live_server, "/api/decision", {
        "id": "aaaa", "status": STATUS_TRACED, "pieces": [{"kind": "rect", "bounds": [2, 48, 3, 49]}],
    })

    assert status == 200
    assert json.loads(body) == {"ok": True}
    record = load_geo(paths)["aaaa"]
    assert shape(record.geometry).bounds == (2.0, 48.0, 3.0, 49.0)


def test_post_decision_http_unknown_meta_gives_404(live_server):
    """A safety rail against `except` shadowing: `UnknownMetaError` inherits from
    `ValueError`, and a badly ordered chain would make it come out as a 400."""
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(live_server, "/api/decision", {
            "id": "zzzz", "status": STATUS_TRACED, "pieces": [{"kind": "country"}],
        })

    assert excinfo.value.code == 404
    body = json.loads(excinfo.value.read())
    assert body["ok"] is False


def test_post_decision_http_invalid_piece_gives_400_and_nothing_is_written(paths, live_server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(live_server, "/api/decision", {
            "id": "aaaa", "status": STATUS_TRACED,
            "pieces": [{"kind": "rect", "bounds": [2, 48, 3, 999]}],
        })

    assert excinfo.value.code == 400
    assert load_geo(paths) == {}


def test_post_decision_http_missing_id_gives_400_naming_the_field(live_server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(live_server, "/api/decision", {"status": STATUS_TRACED, "pieces": [{"kind": "country"}]})

    assert excinfo.value.code == 400
    body = json.loads(excinfo.value.read())
    assert "id" in body["error"]


def test_post_decision_http_invalid_json_body_gives_400(live_server):
    request = urllib.request.Request(
        live_server + "/api/decision", data=b"pas du json", method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)

    assert excinfo.value.code == 400


def test_post_to_an_unknown_route_gives_404(live_server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(live_server, "/api/inexistante", {})

    assert excinfo.value.code == 404


def test_an_oversized_content_length_is_refused_without_reading_the_body(live_server):
    request = urllib.request.Request(
        live_server + "/api/decision", data=b'{"id": "aaaa"}', method="POST"
    )
    request.add_header("Content-Length", "9999999999")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)

    assert excinfo.value.code == 400
    body = json.loads(excinfo.value.read())
    assert "too large" in body["error"]


def test_post_resolve_http_returns_the_clipped_geometry_without_writing_anything(paths, live_server):
    """The clipping preview: the browser cannot intersect, so it asks here — and this
    route must decide nothing and write nothing."""
    status, body = _post(live_server, "/api/resolve", {"pieces": [
        {"kind": "rect", "bounds": [10, 45, 20, 52]},
        {"kind": "clip"},
    ]})

    assert status == 200
    payload = json.loads(body)
    assert shape(payload["geometry"]).bounds == (14.0, 49.0, 20.0, 52.0)
    assert load_geo(paths) == {}


def test_post_resolve_http_area_outside_the_country_gives_400(live_server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(live_server, "/api/resolve", {"pieces": [
            {"kind": "rect", "bounds": [2, 40, 3, 41]},
            {"kind": "clip"},
        ]})

    assert excinfo.value.code == 400
    assert "clipping to the borders" in json.loads(excinfo.value.read())["error"]


def test_post_decision_http_clipping_is_applied_to_what_is_saved(paths, live_server):
    """The clipping seen in the preview has to be the one that goes to disk: the
    descriptor is sent back as-is in the decision, and resolved the same way."""
    status, _ = _post(live_server, "/api/decision", {
        "id": "aaaa", "status": STATUS_TRACED,
        "pieces": [{"kind": "rect", "bounds": [10, 45, 20, 52]}, {"kind": "clip"}],
    })

    assert status == 200
    record = load_geo(paths)["aaaa"]
    assert shape(record.geometry).bounds == (14.0, 49.0, 20.0, 52.0)
    # The kept pieces retain the clip: reopening the meta finds it again.
    assert {"kind": "clip"} in record.pieces


def test_get_queue_http_returns_the_fixture_metas(live_server):
    status, body = _get(live_server, "/api/queue")

    assert status == 200
    payload = json.loads(body)
    assert payload["country"] == "PL"
    assert [item["id"] for item in payload["items"]] == ["aaaa"]
    assert payload["items"][0]["title"] == "titre"


def test_get_category_http_is_a_pass_through(live_server):
    status, body = _get(live_server, "/api/category?text=yellow%20bollards")

    assert status == 200
    assert json.loads(body) == {"category": "infrastructure"}


def test_a_file_under_input_is_served(paths, live_server, monkeypatch):
    racine = paths.data.parent
    (racine / "input").mkdir(parents=True, exist_ok=True)
    (racine / "input" / "photo.jpg").write_bytes(b"contenu-image")
    monkeypatch.setattr("os.getcwd", lambda: str(racine))

    status, body = _get(live_server, "/input/photo.jpg")

    assert status == 200
    assert body == b"contenu-image"


def test_getting_pyproject_toml_outside_static_is_refused(live_server):
    """The reviewer had confirmed this file was served as-is before the restriction:
    this test keeps `ALLOWED_ROOT_PREFIXES` in place."""
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(live_server, "/pyproject.toml")

    assert excinfo.value.code == 404


def test_getting_input_without_a_file_name_does_not_list_the_folder(paths, live_server, monkeypatch):
    """The reviewer had demonstrated that a GET /input/ listed the folder's contents:
    no directory listing must be reachable."""
    racine = paths.data.parent
    (racine / "input").mkdir(parents=True, exist_ok=True)
    (racine / "input" / "photo.jpg").write_bytes(b"contenu-image")
    monkeypatch.setattr("os.getcwd", lambda: str(racine))

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(live_server, "/input/")

    assert excinfo.value.code == 404


def test_post_decision_with_a_same_origin_header_works(paths, live_server):
    """Per the Fetch spec, a browser ALWAYS adds `Origin` on a non-GET/HEAD request,
    same-origin included: so its mere presence must refuse nothing. The header is built
    from the port actually bound by the test server, not from a hard-coded string."""
    request = urllib.request.Request(
        live_server + "/api/decision",
        data=json.dumps({
            "id": "aaaa", "status": STATUS_REJECTED, "pieces": [],
        }).encode("utf-8"),
        method="POST",
    )
    request.add_header("Origin", live_server)
    with urllib.request.urlopen(request, timeout=5) as resp:
        status = resp.status
        body = json.loads(resp.read())

    assert status == 200
    assert body == {"ok": True}
    assert load_geo(paths)["aaaa"].status == STATUS_REJECTED


def test_post_decision_with_a_foreign_origin_is_refused_and_nothing_is_written(paths, live_server):
    """The reviewer demonstrated that a POST with `Origin: https://evil.example` pushed
    the decision through like a legitimate POST: now refused with a 403, and nothing must
    change on disk (not just the status code returned)."""
    request = urllib.request.Request(
        live_server + "/api/decision",
        data=json.dumps({
            "id": "aaaa", "status": STATUS_REJECTED, "pieces": [],
        }).encode("utf-8"),
        method="POST",
    )
    request.add_header("Origin", "https://evil.example")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)

    assert excinfo.value.code == 403
    body = json.loads(excinfo.value.read())
    assert body["ok"] is False
    # The cross-origin decision wrote nothing to disk.
    assert load_geo(paths) == {}


def test_post_decision_without_an_origin_header_still_works(paths, live_server):
    """A non-browser client (e.g. `urllib.request`) sends no Origin header on its POSTs:
    that case has to keep working, safety rail or not."""
    status, body = _post(live_server, "/api/decision", {
        "id": "aaaa", "status": STATUS_REJECTED, "pieces": [],
    })

    assert status == 200
    assert json.loads(body) == {"ok": True}
    assert load_geo(paths)["aaaa"].status == STATUS_REJECTED


# --- Startup port: the interface used to default to AnkiConnect's port. On Windows
# `SO_REUSEADDR` lets a second bind on a listening port succeed, so the server printed
# its URL as if all was well while Anki kept serving that port — the browser got
# `{"apiVersion": "AnkiConnect v.6"}` and nothing else, with no error anywhere. Hence a
# port of our own, and an occupied port detected by probing rather than by trusting bind.


def test_the_default_port_is_not_ankiconnects(paths):
    """Whatever the default becomes, it must never be the port Anki already answers on."""
    assert server.DEFAULT_PORT != server.ANKICONNECT_PORT
    assert server.build_parser().parse_args([]).port == server.DEFAULT_PORT


def test_an_occupied_port_is_seen_as_occupied():
    """The case bind alone does not catch on Windows: a live listener on the port."""
    with HTTPServer(("127.0.0.1", 0), server.Handler) as occupant:
        assert server.port_is_taken("127.0.0.1", occupant.server_address[1]) is True


def test_a_free_port_is_not_reported_as_occupied():
    """The probe must not cry wolf: a port nobody listens on has to read as free, or the
    command would refuse to start at all."""
    with socket.socket() as scout:
        scout.bind(("127.0.0.1", 0))
        port = scout.getsockname()[1]

    assert server.port_is_taken("127.0.0.1", port) is False


def test_main_refuses_an_occupied_port_instead_of_announcing_a_url(monkeypatch, capsys):
    """The heart of the bug: no URL may be printed for a port we do not serve."""
    with HTTPServer(("127.0.0.1", 0), server.Handler) as occupant:
        port = occupant.server_address[1]
        monkeypatch.setattr(sys, "argv", ["cartometa-review", "PL", "--port", str(port)])

        with pytest.raises(SystemExit) as excinfo:
            server.main()

    assert excinfo.value.code == 1
    sortie = capsys.readouterr()
    assert str(port) in sortie.err
    assert "http://127.0.0.1" not in sortie.out
