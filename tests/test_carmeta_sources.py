import pytest

from cartometa.carmeta import mirror
from cartometa.carmeta.analysis import (
    analyse_country,
    candidates_for,
    served_countries,
    unused_paths,
)
from cartometa.carmeta.countries import CountryAssigner
from cartometa.carmeta.rules import Rules, analysis_fingerprint
from tests.carmeta_helpers import lattice, points_file, write_countries


@pytest.fixture(scope="module")
def assigner(tmp_path_factory):
    directory = tmp_path_factory.mktemp("cache")
    write_countries(directory)
    return CountryAssigner(directory)


class Mirror:
    """A state and its compact files, held in memory."""

    def __init__(self, assigner):
        self.assigner = assigner
        self.state = {"files": {}}
        self.compacts = {}
        self.loads = []

    def add(self, path, points, date="2026-05-06T00:00:00Z"):
        sha = f"sha-{path}"
        compact = mirror.decode_points(points_file(points, name=path), self.assigner)
        self.compacts[sha] = compact
        self.state["files"][path] = mirror.file_entry(sha, date, "now", compact)
        return self

    def load(self, sha):
        self.loads.append(sha)
        return self.compacts[sha]

    def analyse(self, country, rules=None):
        return analyse_country(country, self.state, rules or Rules(), self.load,
                               self.assigner.iso)


def _aa(tags_of, n=40):
    return lattice(tags_of, n=n)


def _bb(tags_of, n=40):
    return lattice(tags_of, n=n, lng0=22.0)


def _half(tag):
    return lambda row, column: [tag] if column < 20 else []


def _sources(analysis):
    return {s["path"]: s["families"] for s in analysis["sources"]}


def test_the_newest_primary_file_wins(assigner):
    m = Mirror(assigner)
    m.add("old.json", _aa(_half("Blue 2023")), date="2026-01-01T00:00:00Z")
    m.add("new.json", _aa(_half("Blue 2024")), date="2026-08-01T00:00:00Z")

    analysis = m.analyse("AA")

    assert _sources(analysis) == {"new.json": ["car_year"]}
    assert [row["canonical"] for row in analysis["rows"]] == ["Blue 2024"]
    assert analysis["sources"][0]["role"] == "primary"
    assert analysis["sources"][0]["points"] == 1600
    assert analysis["rules_fingerprint"] == analysis_fingerprint(Rules())


def test_at_equal_dates_the_file_with_the_most_points_wins(assigner):
    m = Mirror(assigner)
    m.add("small.json", _aa(_half("Blue 2023"), n=30))
    m.add("large.json", _aa(_half("Blue 2024"), n=40))

    assert [c.path for c in candidates_for("AA", m.state, Rules())] == [
        "large.json", "small.json"]


def test_a_family_the_newest_file_dropped_comes_from_the_previous_one(assigner):
    m = Mirror(assigner)
    m.add("old.json", _aa(lambda r, c: ["Blue 2023", "©2025"] if c < 20 else ["©2026"]),
          date="2026-01-01T00:00:00Z")
    m.add("new.json", _aa(_half("Blue 2024")), date="2026-08-01T00:00:00Z")

    analysis = m.analyse("AA")

    assert _sources(analysis) == {"new.json": ["car_year"], "old.json": ["copyright"]}
    by_tag = {row["canonical"]: analysis["sources"][row["source"]]["path"]
              for row in analysis["rows"]}
    # The old file's car tags are NOT resurrected: only its copyrights are read.
    assert by_tag == {"Blue 2024": "new.json", "©2025": "old.json", "©2026": "old.json"}


def test_a_family_needs_a_tag_large_enough_for_a_zone(assigner):
    m = Mirror(assigner)
    m.add("old.json", _aa(lambda r, c: ["©2025"] if c < 20 else []),
          date="2026-01-01T00:00:00Z")
    # 20 copyright points in the new file: not enough to say it has the family.
    m.add("new.json", _aa(lambda r, c: ["Blue 2024"] + (["©2026"] if r < 4 and c < 5 else [])),
          date="2026-08-01T00:00:00Z")

    assert _sources(m.analyse("AA"))["old.json"] == ["copyright"]


def test_a_primary_file_beats_a_multi_country_one(assigner):
    m = Mirror(assigner)
    m.add("continent.json", _aa(_half("Blue 2022")) + _bb(_half("Blue 2022"), n=50),
          date="2026-09-01T00:00:00Z")
    m.add("own.json", _aa(_half("Blue 2024")), date="2026-01-01T00:00:00Z")

    assert _sources(m.analyse("AA")) == {"own.json": ["car_year"]}


def test_a_country_without_a_primary_file_takes_its_richest_multi_country_one(assigner):
    m = Mirror(assigner)
    m.add("continent.json", _aa(_half("Blue 2022")) + _bb(_half("Blue 2022"), n=50))
    m.add("thin.json", _aa(_half("Blue 2021"), n=32) + _bb(_half("Blue 2021"), n=60))

    analysis = m.analyse("AA")

    assert _sources(analysis) == {"continent.json": ["car_year"]}
    assert analysis["sources"][0]["role"] == "multi"


def test_a_handful_of_points_across_the_border_serves_nobody(assigner):
    m = Mirror(assigner)
    # 900 points in AA out of 3 400: neither primary nor multi-country for AA.
    m.add("bb.json", _aa(_half("Blue 2024"), n=30) + _bb(_half("Blue 2024"), n=50))

    analysis = m.analyse("AA")

    assert analysis["sources"] == [] and analysis["rows"] == []
    assert served_countries(m.state, Rules()) == ["BB"]


def test_a_pin_forces_a_file_for_a_country_or_for_one_family(assigner):
    m = Mirror(assigner)
    m.add("old.json", _aa(lambda r, c: ["Blue 2023", "©2025"] if c < 20 else ["©2026"]),
          date="2026-01-01T00:00:00Z")
    m.add("new.json", _aa(lambda r, c: ["Blue 2024", "©2025"] if c < 20 else ["©2026"]),
          date="2026-08-01T00:00:00Z")

    whole = Rules(pin={"AA": "old.json"})
    assert _sources(m.analyse("AA", whole)) == {"old.json": ["car_year", "copyright"]}
    assert m.analyse("AA", whole)["sources"][0]["role"] == "pinned"

    one = Rules(pin={"AA|copyright": "old.json"})
    assert _sources(m.analyse("AA", one)) == {"new.json": ["car_year"],
                                             "old.json": ["copyright"]}


def test_a_pin_on_a_file_the_mirror_does_not_hold_is_an_error(assigner):
    m = Mirror(assigner).add("new.json", _aa(_half("Blue 2024")))

    with pytest.raises(ValueError, match="gone.json"):
        m.analyse("AA", Rules(pin={"AA": "gone.json"}))


def test_an_excluded_path_is_never_a_source(assigner):
    m = Mirror(assigner)
    m.add("old.json", _aa(_half("Blue 2023")), date="2026-01-01T00:00:00Z")
    m.add("new.json", _aa(_half("Blue 2024")), date="2026-08-01T00:00:00Z")

    assert _sources(m.analyse("AA", Rules(exclude=["new.json"]))) == {"old.json": ["car_year"]}


def test_each_file_is_loaded_once_per_country(assigner):
    m = Mirror(assigner)
    m.add("old.json", _aa(lambda r, c: ["©2025"] if c < 20 else ["©2026"]),
          date="2026-01-01T00:00:00Z")
    m.add("new.json", _aa(_half("Blue 2024")), date="2026-08-01T00:00:00Z")

    m.analyse("AA")

    assert sorted(m.loads) == ["sha-new.json", "sha-old.json"]


def test_files_that_feed_no_country_are_named(assigner):
    m = Mirror(assigner)
    m.add("old.json", _aa(_half("Blue 2023")), date="2026-01-01T00:00:00Z")
    m.add("new.json", _aa(_half("Blue 2024")), date="2026-08-01T00:00:00Z")
    m.state["files"]["README.md"] = {"sha": "x", "kind": "other"}

    assert unused_paths(m.state, {"AA": m.analyse("AA")}) == ["old.json"]


def test_the_analysis_is_deterministic(assigner):
    m = Mirror(assigner).add("new.json", _aa(_half("Blue 2024")))

    assert m.analyse("AA") == m.analyse("AA")
