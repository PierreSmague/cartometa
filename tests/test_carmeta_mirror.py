import io
import json
import zipfile

import numpy as np
import pytest

from cartometa.carmeta import github, mirror
from cartometa.carmeta.countries import CountryAssigner
from cartometa.carmeta.paths import CarmetaPaths
from tests.carmeta_helpers import point, points_file, write_countries


@pytest.fixture
def assigner(tmp_path):
    write_countries(tmp_path / "data" / "cache")
    return CountryAssigner(tmp_path / "data" / "cache")


POINTS = [
    point(5.0, 5.0, ["Blue 2024", "©2025"], pano="a", heading=12.5),
    point(5.1, 5.0, ["Blue 2024"], pano="b"),
    point(5.0, 25.0, ["©2025", "Blue 2024"], pano="c"),      # country BB, same combo as a
    point(5.0, 15.0, ["Blue 2024"], pano="d"),               # in no country
    point(-85.0, 5.0, ["───Month───"], pano="e"),            # dummy separator point
    {"lat": 5.0, "lng": 5.0, "extra": {"tags": ["Blue 2024"]}},   # no panoId
    point(5.2, 5.0, [], pano="f"),                           # untagged, kept
]


def test_a_bare_json_is_reduced_to_arrays(assigner):
    compact = mirror.decode_points(
        points_file(POINTS, name="Test", colors={"Blue 2024": [0, 0, 255]}), assigner)

    assert compact.name == "Test"
    assert [p.decode() for p in compact.pano] == ["a", "b", "c", "d", "f"]
    assert compact.heading[0] == pytest.approx(12.5)
    assert compact.codes == ["AA", "BB"]
    assert compact.country.tolist() == [0, 0, 1, -1, 0]
    assert compact.country_counts() == {"AA": 3, "BB": 1}
    assert compact.points_of("AA").tolist() == [0, 1, 4]
    assert compact.points_of("ZZ").tolist() == []
    # Tags go through combinations; the order of a point's tags does not matter.
    assert compact.combo[0] == compact.combo[2]
    assert sorted(compact.tags[i] for i in compact.combos[compact.combo[0]]) == ["Blue 2024", "©2025"]
    assert compact.combos[compact.combo[4]] == []
    assert compact.colors == {"Blue 2024": [0, 0, 255]}
    assert compact.order == {"Blue 2024": 0}


def test_a_zip_holds_one_json(assigner):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__MACOSX/._junk", b"junk")
        archive.writestr("Thailand.json", points_file(POINTS))

    compact = mirror.decode_points(buffer.getvalue(), assigner)

    assert len(compact.lat) == 5


@pytest.mark.parametrize("raw", [
    b"# A readme", b"[1, 2, 3]", b'{"name": "no coordinates"}', b"PK\x03\x04broken", b"",
])
def test_what_is_not_a_points_file_gives_none(assigner, raw):
    assert mirror.decode_points(raw, assigner) is None


def test_an_empty_points_file_is_still_a_points_file(assigner):
    compact = mirror.decode_points(points_file([]), assigner)

    assert len(compact.lat) == 0 and compact.country_counts() == {}


def test_the_compact_cache_round_trips(assigner, tmp_path):
    paths = CarmetaPaths(tmp_path / "data")
    compact = mirror.decode_points(points_file(POINTS, colors={"Blue 2024": "#00f"}), assigner)

    mirror.store_compact(paths, "abc123", compact)
    loaded = mirror.load_compact(paths, "abc123")

    for name in ("lat", "lng", "heading", "pano", "combo", "country"):
        assert np.array_equal(getattr(loaded, name), getattr(compact, name)), name
    assert (loaded.name, loaded.tags, loaded.combos, loaded.colors, loaded.order,
            loaded.codes) == (compact.name, compact.tags, compact.combos,
                              compact.colors, compact.order, compact.codes)
    assert [p.name for p in paths.files.iterdir()] == ["abc123.npz"]


@pytest.mark.parametrize("path, expected", [
    ("Europe/France/France Vali 27.01.26.json", True),
    ("Asia/Thailand/Thailand 190K.json.zip", True),
    ("CentralAmerica/CostaRica/CostaRica-CR-17.05.26", True),
    ("README.md", False),
    ("LICENSE", False),
    ("Europe/README.md", False),
    (".github/workflows/x.yml", False),
    ("Europe/.DS_Store", False),
    ("docs/preview.png", False),
])
def test_documentation_is_never_downloaded(path, expected):
    assert mirror.is_candidate(path) is expected


def _tree(files):
    return github.Tree("root", {p: github.Blob(sha, 1) for p, sha in files.items()})


def test_the_diff_names_new_modified_and_deleted_paths():
    state = {"files": {"Europe/a.json": {"sha": "1"}, "Europe/b.json": {"sha": "2"},
                       "Europe/gone.json": {"sha": "3"}}}
    tree = _tree({"Europe/a.json": "1", "Europe/b.json": "2bis", "Europe/c.json": "4",
                  "README.md": "5"})

    result = mirror.diff(state, tree)

    assert (result.new, result.modified, result.deleted) == (
        ["Europe/c.json"], ["Europe/b.json"], ["Europe/gone.json"])
    assert result.to_fetch == ["Europe/b.json", "Europe/c.json"]
    assert result


def test_nothing_changed_is_falsy():
    state = {"files": {"Europe/a.json": {"sha": "1"}}}

    assert not mirror.diff(state, _tree({"Europe/a.json": "1", "README.md": "9"}))


def test_the_state_starts_empty_and_round_trips(tmp_path):
    paths = CarmetaPaths(tmp_path / "data")
    state = mirror.load_state(paths)
    assert state == {"tree_sha": None, "checked_at": None, "dirty": [], "files": {}}

    state["dirty"] = ["MX", "AT", "MX"]
    state["files"]["b"] = {"sha": "2"}
    state["files"]["a"] = {"sha": "1"}
    mirror.save_state(paths, state)

    reloaded = mirror.load_state(paths)
    assert reloaded["dirty"] == ["AT", "MX"]
    assert list(reloaded["files"]) == ["a", "b"]


def test_a_state_entry_describes_what_was_fetched(assigner):
    compact = mirror.decode_points(points_file(POINTS, name="Test"), assigner)

    entry = mirror.file_entry("sha1", "2026-05-06T13:05:16Z", "now", compact)

    assert entry == {"sha": "sha1", "commit_date": "2026-05-06T13:05:16Z",
                     "fetched_at": "now", "kind": "points", "name": "Test",
                     "points": 5, "countries": {"AA": 3, "BB": 1}}
    assert mirror.file_entry("sha2", "d", "now", None)["kind"] == "other"
