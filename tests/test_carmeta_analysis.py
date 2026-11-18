import pytest

from cartometa.carmeta import mirror
from cartometa.carmeta.analysis import FileCountry, _hex_colour
from cartometa.carmeta.countries import CountryAssigner
from cartometa.carmeta.rules import LexiconEntry, Rules
from cartometa.review.pieces import resolve_pieces
from tests.carmeta_helpers import lattice, points_file, write_countries

ALL = {"car_year", "car", "copyright", "antenna", "bl", "blur", "exposed", "snow",
       "smallcam", "unknown"}


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    directory = tmp_path_factory.mktemp("cache")
    write_countries(directory)
    return directory


@pytest.fixture(scope="module")
def assigner(cache):
    return CountryAssigner(cache)


def _rules():
    return Rules(lexicon={"Blue": LexiconEntry("Blue car"),
                          "Antenna": LexiconEntry("Antenna")})


def _view(assigner, tags_of, n=40, colors=None, rules=None):
    compact = mirror.decode_points(points_file(lattice(tags_of, n=n), colors=colors), assigner)
    return FileCountry(compact, "AA", rules or _rules(), assigner.iso)


def _rows(view, families=ALL):
    return {row["canonical"]: row for row in view.rows(families)}


def test_two_spellings_of_a_tag_are_merged_and_their_points_counted_once(assigner):
    def tags_of(row, column):
        if column >= 20:
            return []
        if row % 3 == 0:
            return ["Blue 24 (NA)"]
        if row % 3 == 1:
            return ["Blue 2024 (NA)"]
        return ["Blue 24 (NA)", "Blue Car 2024 (NA)"]      # both spellings on one point

    rows = _rows(_view(assigner, tags_of))

    assert list(rows) == ["Blue 2024 (NA)"]
    row = rows["Blue 2024 (NA)"]
    assert row["points"] == 800
    assert row["raw_tags"] == ["Blue 2024 (NA)", "Blue 24 (NA)", "Blue Car 2024 (NA)"]
    assert (row["family"], row["lexicon_key"], row["year"], row["antenna"]) == (
        "car_year", "Blue", 2024, "NA")


def test_a_tag_covered_by_finer_car_year_tags_is_a_parent(assigner):
    def tags_of(row, column):
        if column < 20:
            # The antenna coverage splits into two finer, strictly smaller tags.
            return ["Blue 2023 (A)" if row < 25 else "Blue 2022 (A)", "Antenna"]
        return ["Blue 2024 (NA)"]

    rows = _rows(_view(assigner, tags_of))

    assert (rows["Antenna"]["verdict"], rows["Antenna"]["reason"]) == (
        "écarté", "couvert par des tags plus fins")
    assert rows["Antenna"]["pieces"] is None
    # Its measures are still there for the report.
    assert rows["Antenna"]["zones"] == 1 and rows["Antenna"]["gain"] > 0.3
    assert rows["Blue 2023 (A)"]["verdict"] == "retenu"


def test_an_independent_antenna_stays_a_candidate(assigner):
    def tags_of(row, column):
        tags = ["Blue 2023"] if column < 20 else ["Blue 2024"]
        return tags + (["Antenna"] if row < 20 else [])

    rows = _rows(_view(assigner, tags_of))

    assert rows["Antenna"]["verdict"] == "retenu"
    assert rows["Antenna"]["pieces"] is not None


def test_a_parent_needs_its_children_to_cover_it(assigner):
    def tags_of(row, column):
        if column < 20:
            # Only the top quarter of the antenna coverage has a finer tag.
            return ["Antenna"] + (["Blue 2023 (A)"] if row < 10 else [])
        return []

    assert _rows(_view(assigner, tags_of))["Antenna"]["verdict"] == "retenu"


def test_a_copyright_is_never_a_parent(assigner):
    def tags_of(row, column):
        return ["©2026", "Smallcam 2026"] if column < 20 else ["©2025"]

    rows = _rows(_view(assigner, tags_of))

    assert rows["©2026"]["verdict"] == "retenu"
    assert rows["Smallcam 2026"]["verdict"] == "retenu"


def test_each_line_of_the_verdict_table(assigner):
    def tags_of(row, column):
        tags = []
        if row < 4 and column < 5:
            tags.append("Tiny")                                   # 20 points
        if row % 6 == 0 and column % 6 == 0:
            tags.append("Scattered")                              # lone points only
        if (row < 6 and column < 6) or (row >= 12 and row % 6 == 0 and column % 6 == 0):
            tags.append("Mostly isolated")                        # one zone, 31 % captured
        if (row + column) % 3 == 0:
            tags.append("Everywhere")
        if column < 50:
            tags.append("Five sixths")
        if column < 30:
            tags.append("Half")
        return tags

    rows = _rows(_view(assigner, tags_of, n=60))

    assert {name: (row["verdict"], row["reason"]) for name, row in rows.items()} == {
        "Tiny": ("écarté", "moins de 30 points"),
        "Scattered": ("écarté", "aucune zone de 30 points"),
        "Mostly isolated": ("écarté", "points surtout isolés"),
        "Everywhere": ("écarté", "non discriminant"),
        "Five sixths": ("arbitrage", "discriminance limite"),
        "Half": ("retenu", ""),
    }
    # A footprint for every tag the gain lines decided — the dropped one too.
    assert {name for name, row in rows.items() if row["pieces"] is not None} == {
        "Everywhere", "Five sixths", "Half"}
    for name in ("Tiny", "Scattered", "Mostly isolated"):
        assert rows[name]["rep"] is None and rows[name]["cells"] is None
    assert rows["Tiny"]["gain"] is None and rows["Scattered"]["gain"] is None
    assert rows["Mostly isolated"]["capture"] == pytest.approx(36 / 116, abs=1e-3)


def test_a_retained_row_carries_what_the_meta_needs(assigner, cache):
    def tags_of(row, column):
        return ["Blue 2024"] if column < 20 else []

    view = _view(assigner, tags_of, colors={"Blue 2024": [0, 64, 255]})
    row = _rows(view)["Blue 2024"]

    assert row["color"] == "#0040ff"
    assert row["rep"]["pano"].startswith("pano")
    assert 2.0 <= row["rep"]["lat"] <= 2.4 and row["rep"]["heading"] == 90.0
    assert [piece["kind"] for piece in row["pieces"]] == ["polygon", "clip"]
    assert resolve_pieces(row["pieces"], "AA", cache).area > 0
    assert isinstance(row["cells"], str)
    grid = view.grid()
    assert grid["link"] == pytest.approx(3.0, abs=0.05) and grid["W"] * grid["H"] > 0


def test_only_the_requested_families_are_analysed(assigner):
    def tags_of(row, column):
        return ["Blue 2024", "©2025"] if column < 20 else ["©2026"]

    view = _view(assigner, tags_of)

    assert view.families(30) == {"car_year", "copyright"}
    assert list(_rows(view, {"copyright"})) == ["©2025", "©2026"]


def test_points_of_other_countries_are_left_out(assigner):
    points = lattice(lambda r, c: ["Blue 2024"]) + lattice(
        lambda r, c: ["Blue 2024", "Blue 2023"], lng0=22.0)
    compact = mirror.decode_points(points_file(points), assigner)

    view = FileCountry(compact, "AA", _rules(), assigner.iso)

    assert view.points == {"Blue 2024": 1600}


@pytest.mark.parametrize("value, expected", [
    ([255, 0, 128], "#ff0080"), ("#3366CC", "#3366cc"), ("abc", "#aabbcc"),
    ([300, 0, 0], None), ("blue", None), (None, None), ({"r": 1}, None),
    ([12.4, 0, 255.0], "#0c00ff"),
])
def test_colours_are_normalised_or_dropped(value, expected):
    assert _hex_colour(value) == expected
