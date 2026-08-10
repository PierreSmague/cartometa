import json

import pytest

from cartometa.geo.reference import DATASET_NAME
from cartometa.models import STATUS_PROPOSED, STATUS_TRACED, GeoRecord
from cartometa.review.store import CountryPaths, build_queue, load_geo, load_metas, save_geo
from cartometa.tagged.importer import ImportReport, TaggedFileError, import_tagged, proposal_id


def _point(lat, lng, tags):
    return {"lat": lat, "lng": lng, "extra": {"tags": tags}}


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    (d / "cache").mkdir(parents=True)
    (d / "cache" / DATASET_NAME).write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"ISO_A2": c, "ISO_A2_EH": c},
             "geometry": {"type": "Polygon", "coordinates": [[
                 [w, 0.0], [w + 10.0, 0.0], [w + 10.0, 10.0], [w, 10.0], [w, 0.0],
             ]]}}
            for c, w in (("AA", 0.0), ("BB", 20.0))
        ],
    }), "utf-8")
    return d


def _source(tmp_path, points, name="fichier test"):
    f = tmp_path / "source.json"
    f.write_text(json.dumps({"name": name, "customCoordinates": points}), "utf-8")
    return f


def test_one_meta_per_tag_and_country(data_dir, tmp_path):
    src = _source(tmp_path, [
        _point(5.0, 5.0, ["Ring"]), _point(5.01, 5.01, ["Ring"]),
        _point(5.0, 25.0, ["Ring"]),          # même tag, autre pays
        _point(5.02, 5.02, ["Short", "Ring"]),  # deux tags -> deux metas
    ])

    report = import_tagged(data_dir, src, mode="route", category="car")

    aa = CountryPaths(data_dir, "AA")
    metas = {m["title"]: m for m in load_metas(aa)}
    assert set(metas) == {"Ring", "Short"}
    assert metas["Ring"]["description"] == "Ring"
    assert metas["Ring"]["category"] == "car"
    assert metas["Ring"]["origin"] == "tagged"
    assert metas["Ring"]["id"] == proposal_id("fichier test", "Ring", "AA")
    bb = CountryPaths(data_dir, "BB")
    assert {m["title"] for m in load_metas(bb)} == {"Ring"}
    assert {(r.tag, r.country) for r in report.rows} == {
        ("Ring", "AA"), ("Ring", "BB"), ("Short", "AA"),
    }


def test_proposals_land_in_the_review_queue_with_pieces(data_dir, tmp_path):
    src = _source(tmp_path, [_point(5.0, 5.0, ["Ring"]), _point(5.01, 5.01, ["Ring"])])
    import_tagged(data_dir, src, mode="route", category="car")

    queue = build_queue(CountryPaths(data_dir, "AA"))

    (item,) = queue["items"]
    assert item["status"] == STATUS_PROPOSED
    assert item["pieces"][0]["kind"] == "polygon"


def test_rerunning_the_import_changes_nothing(data_dir, tmp_path):
    src = _source(tmp_path, [_point(5.0, 5.0, ["Ring"]), _point(5.01, 5.01, ["Ring"])])
    aa = CountryPaths(data_dir, "AA")

    import_tagged(data_dir, src, mode="route", category="car")
    before = (aa.tagged_metas.read_bytes(), aa.geo.read_bytes())
    report = import_tagged(data_dir, src, mode="route", category="car")

    assert (aa.tagged_metas.read_bytes(), aa.geo.read_bytes()) == before
    assert all(r.action == "inchangée" for r in report.rows)


def test_a_decided_meta_is_never_overwritten(data_dir, tmp_path):
    src = _source(tmp_path, [_point(5.0, 5.0, ["Ring"]), _point(5.01, 5.01, ["Ring"])])
    import_tagged(data_dir, src, mode="route", category="car")
    aa = CountryPaths(data_dir, "AA")
    pid = proposal_id("fichier test", "Ring", "AA")
    mine = {"kind": "polygon", "ring": [[5.0, 5.0], [6.0, 5.0], [6.0, 6.0]]}
    records = load_geo(aa)
    records[pid] = GeoRecord(id=pid, geometry=None, pieces=[mine], status=STATUS_TRACED)
    save_geo(aa, records)

    report = import_tagged(data_dir, src, mode="route", category="car")

    assert load_geo(aa)[pid].status == STATUS_TRACED
    assert load_geo(aa)[pid].pieces == [mine]
    (row,) = report.rows
    assert row.action == "sautée (décidée)"


def test_dry_run_writes_nothing(data_dir, tmp_path):
    src = _source(tmp_path, [_point(5.0, 5.0, ["Ring"])])

    report = import_tagged(data_dir, src, mode="route", category="car", dry_run=True)

    assert report.rows
    assert not CountryPaths(data_dir, "AA").tagged_metas.exists()
    assert not CountryPaths(data_dir, "AA").geo.exists()


def test_untagged_and_unplaced_points_are_counted(data_dir, tmp_path):
    src = _source(tmp_path, [
        _point(5.0, 5.0, ["Ring"]),
        _point(5.0, 5.1, []),          # sans tag
        _point(5.0, 15.0, ["Ring"]),   # à > 10 km de tout pays
    ])

    report = import_tagged(data_dir, src, mode="route", category="car")

    assert report.untagged == 1
    assert report.unplaced == 1


def test_an_unreadable_file_fails_frankly(data_dir, tmp_path):
    f = tmp_path / "vide.json"
    f.write_text(json.dumps({"name": "x"}), "utf-8")
    with pytest.raises(TaggedFileError):
        import_tagged(data_dir, f, mode="route", category="car")


def test_zone_mode_uses_the_hull(data_dir, tmp_path):
    # Quatre coins d'un carré de ~30 km : une seule zone, pas quatre pastilles.
    src = _source(tmp_path, [
        _point(5.0, 5.0, ["Hut"]), _point(5.27, 5.0, ["Hut"]),
        _point(5.0, 5.27, ["Hut"]), _point(5.27, 5.27, ["Hut"]),
    ])

    import_tagged(data_dir, src, mode="zone", category="architecture")

    records = load_geo(CountryPaths(data_dir, "AA"))
    (record,) = records.values()
    assert len(record.pieces) == 1
