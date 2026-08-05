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


def test_the_queue_merges_both_sources(paths):
    queue = build_queue(paths)

    assert [item["id"] for item in queue["items"]] == ["aaaa", "bbbb", "man-1a2b"]


def test_the_queue_exposes_the_image_path_as_a_url(paths):
    queue = build_queue(paths)

    images = {item["id"]: item["image"] for item in queue["items"]}
    assert images["aaaa"] == "/input/aaaa.webp"
    assert images["man-1a2b"] == "/data/manual/PL/images/man-1a2b.png"


def test_the_queue_skips_already_handled_metas_by_default(paths):
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, [{"kind": "rect", "bounds": [2, 48, 3, 49]}])

    queue = build_queue(paths)

    assert [item["id"] for item in queue["items"]] == ["bbbb", "man-1a2b"]
    assert queue["done"] == 1
    assert queue["total"] == 3


def test_a_rejected_meta_does_not_come_back_in_the_queue(paths):
    set_decision(paths, "bbbb", STATUS_REJECTED, None, [])

    assert "bbbb" not in {item["id"] for item in build_queue(paths)["items"]}


def test_include_all_reopens_everything_with_its_pieces(paths):
    morceaux = [{"kind": "admin1", "code": "POL-1"}]
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, morceaux)

    queue = build_queue(paths, include_all=True)

    rouverte = next(item for item in queue["items"] if item["id"] == "aaaa")
    assert rouverte["status"] == STATUS_TRACED
    assert rouverte["pieces"] == morceaux


def test_done_counts_decided_metas_absent_from_the_queue_in_both_modes(paths):
    """`done` has to stay consistent with `done + len(items) == total`:

    by default the decided meta is excluded from the queue (`done` is 1); under
    `include_all` it is put back in (`done` falls back to 0), otherwise the client's
    progress formula would exceed the total (`67/37` observed on a country of 37 metas /
    30 decided).
    """
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, [{"kind": "country"}])

    defaut = build_queue(paths)
    assert defaut["done"] == 1
    assert defaut["done"] + len(defaut["items"]) == defaut["total"]

    tout = build_queue(paths, include_all=True)
    assert tout["done"] == 0
    assert tout["done"] + len(tout["items"]) == tout["total"]


def test_a_never_handled_meta_arrives_without_status_or_piece(paths):
    item = build_queue(paths)["items"][0]

    assert item["status"] is None
    assert item["pieces"] == []


def test_the_decision_is_read_back_identically(paths):
    morceaux = [{"kind": "rect", "bounds": [2.0, 48.0, 3.0, 49.0]}]
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, morceaux)

    record = load_geo(paths)["aaaa"]

    assert record.geometry == CARRE
    assert record.pieces == morceaux
    assert record.status == STATUS_TRACED


def test_the_geojson_is_written_compact(paths):
    """Indentation cost a measured factor of 4 on the real files: RU.geojson weighed
    90 MB (4.1 million lines) against 25 MB compact. Every coordinate on its own line,
    versioned, on every redraw."""
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, [{"kind": "country"}])

    texte = paths.geo.read_text("utf-8")

    assert "\n" not in texte.strip()


def test_the_coordinates_are_rounded_to_five_decimals(paths):
    """Five decimals ≈ 1 m on the ground: plenty for a meta footprint, and ~10 % smaller
    than the fifteen decimals of a serialised float64. The `pieces` are rounded too —
    they carry nothing but coordinates."""
    fin = {"type": "Polygon", "coordinates": [[
        [2.123456789, 48.987654321], [3.111111111, 48.0],
        [3.0, 49.222222222], [2.123456789, 48.987654321],
    ]]}
    morceaux = [{"kind": "polygon", "ring": [[2.123456789, 48.987654321]]}]

    set_decision(paths, "aaaa", STATUS_TRACED, fin, morceaux)

    record = load_geo(paths)["aaaa"]
    assert record.geometry["coordinates"][0][0] == [2.12346, 48.98765]
    assert record.pieces[0]["ring"] == [[2.12346, 48.98765]]


# A valid ring whose rounding to 5 decimals is invalid: the vertex (0.4, 0.399996)
# joins the already present (0.4, 0.4), and the ring then passes twice through the same
# point. It happened on the real data: 8 footprints out of 3617 degenerated that way
# during the first migration.
ANNEAU_FRAGILE = [
    [0.0, 0.0], [0.8, 0.0], [0.4, 0.399996], [0.8, 0.8], [0.0, 0.8], [0.4, 0.4],
    [0.0, 0.0],
]


def test_a_geometry_that_rounding_would_invalidate_keeps_its_precision(paths):
    from shapely.geometry import shape

    fragile = {"type": "Polygon", "coordinates": [ANNEAU_FRAGILE]}
    # Preconditions: valid as-is, invalid once rounded — otherwise this test would prove
    # nothing about the fallback.
    assert shape(fragile).is_valid
    arrondie = {"type": "Polygon", "coordinates": [
        [[round(x, 5), round(y, 5)] for x, y in ANNEAU_FRAGILE]
    ]}
    assert not shape(arrondie).is_valid

    set_decision(paths, "aaaa", STATUS_TRACED, fragile, [{"kind": "country"}])

    record = load_geo(paths)["aaaa"]
    assert shape(record.geometry).is_valid
    assert record.geometry["coordinates"] == fragile["coordinates"]


def test_a_piece_ring_that_rounding_would_invalidate_keeps_its_precision(paths):
    """The `pieces` are what makes reopening a meta possible: `resolve_pieces` rebuilds
    polygons from their rings, and a ring turned invalid by rounding would break that
    reopening."""
    morceaux = [{"kind": "polygon", "ring": ANNEAU_FRAGILE}]

    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, morceaux)

    record = load_geo(paths)["aaaa"]
    assert record.pieces[0]["ring"] == ANNEAU_FRAGILE


def test_undoing_removes_the_meta_from_the_file(paths):
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, [{"kind": "country"}])

    clear_decision(paths, "aaaa")

    assert "aaaa" not in load_geo(paths)


def test_undoing_a_meta_with_no_decision_raises(paths):
    with pytest.raises(UnknownMetaError):
        clear_decision(paths, "aaaa")


def test_deciding_on_an_unknown_meta_raises(paths):
    with pytest.raises(UnknownMetaError):
        set_decision(paths, "zzzz", STATUS_TRACED, CARRE, [{"kind": "country"}])


def test_an_unknown_status_is_refused(paths):
    with pytest.raises(ValueError):
        set_decision(paths, "aaaa", "corrigé", CARRE, [{"kind": "country"}])


def test_a_country_with_no_imported_file(tmp_path):
    """A country may have only manual metas."""
    paths = CountryPaths(tmp_path / "data", "XX")
    paths.manual_metas.parent.mkdir(parents=True)
    paths.manual_metas.write_text(json.dumps([_meta("man-abcd", country="XX")]), "utf-8")

    assert [m["id"] for m in load_metas(paths)] == ["man-abcd"]


def test_a_country_with_no_source_at_all(tmp_path):
    assert load_metas(CountryPaths(tmp_path / "data", "XX")) == []
