"""The real analysis against the figures the maintainer validated.

Needs the carmeta mirror (`cartometa-carmeta sync`, about 1.3 GB downloaded
once): skipped when `data/cache/carmeta/analysis/` is absent. The reference is
`expected-verdicts.json`, produced by the design prototype on the repository as
of 2026-11-15; a file committed again since then is left out of the comparison.
"""
import collections
import json
from pathlib import Path

import pytest

from cartometa.carmeta import mirror
from cartometa.carmeta.analysis import unused_paths
from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.rules import load_rules
from cartometa.carmeta.sync import load_analyses
from cartometa.carmeta.tags import classify

ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / "docs" / "specs" / "2026-11-18-carmeta-spike"
PATHS = CarmetaPaths(ROOT / "data")

pytestmark = [
    pytest.mark.carmeta_cache,
    pytest.mark.skipif(not PATHS.analysis_dir.exists(),
                       reason="no carmeta mirror: run `cartometa-carmeta sync`"),
]

# The gain is what the verdict hangs on; zone counts and capture are only shown.
GAIN_TOLERANCE = 0.02

# Every row whose figures differ from the prototype's, and why. The verdict
# and its reason must match even for these: only the figures may differ. A
# difference that is not listed here fails the test.
_LOOSE_US = (
    "US tag chained loosely (38 to 52 % of its points in zones): its zone count "
    "moves with a 1 % change of the link distance L, and L derives from a "
    "300-point sample of an 846 433-point cloud. Measured: 21 to 24 zones for "
    "`Blue 2019` between 0.97·L and 1.03·L. Same verdict.")
KNOWN_GAPS = {
    ("PE", "Smallcam 2025"): (
        "The Peru file lists this tag twice on each of its points. The prototype "
        "counted the point twice (2 866 points, 49 % captured); the product counts "
        "it once (1 433 points, 98 % captured)."),
    ("US", "Blue 2019"): _LOOSE_US,
    ("US", "Blue 2022"): _LOOSE_US,
    ("US", "Blue Exp 2021"): _LOOSE_US,
    ("US", "Gray Exp 2024"): _LOOSE_US,
    ("US", "No Car 2019"): _LOOSE_US,
    ("US", "No Car 2022"): _LOOSE_US,
    ("US", "Striped 2021"): _LOOSE_US,
}
# Families the prototype did not keep at all: bare descriptors (`Black`) and
# words nothing recognises, which the product sends to arbitration.
NEW_FAMILIES = {"car", "unknown"}


@pytest.fixture(scope="module")
def analyses():
    return load_analyses(PATHS)


@pytest.fixture(scope="module")
def comparable(analyses):
    """Countries whose source files are still the ones the prototype read."""
    dates = json.loads((SPIKE / "file_dates.json").read_text("utf-8"))
    # Day precision: the prototype recorded author dates, the API gives
    # committer dates, a few minutes later.
    return {
        country for country, analysis in analyses.items()
        if all(dates.get(source["path"], "")[:10] == source["date"][:10]
               for source in analysis["sources"])
    }


def _expected(rules):
    rows = collections.defaultdict(list)
    for row in json.loads((SPIKE / "expected-verdicts.json").read_text("utf-8")):
        canonical = classify(row["tag"], frozenset(), rules.lexicon_index)
        rows[(row["country"], canonical.text)].append(row)
    return rows


def test_the_verdicts_are_the_ones_the_maintainer_validated(analyses, comparable):
    assert comparable, "every source file changed since the prototype: nothing to compare"
    rules = load_rules(PATHS.rules)
    product = {(country, row["canonical"]): row
               for country in comparable for row in analyses[country]["rows"]}
    problems = []
    compared = 0
    for key, expected_rows in sorted(_expected(rules).items()):
        if key[0] not in comparable:
            continue
        compared += 1
        row = product.get(key)
        if row is None:
            problems.append(f"{key}: missing from the product")
            continue
        if len(expected_rows) > 1:
            # Two spellings the product merged: only the verdict can be compared.
            if key not in KNOWN_GAPS:
                problems.append(f"{key}: merged from {len(expected_rows)} tags, unexplained")
            continue
        (expected,) = expected_rows
        if (row["verdict"], row["reason"]) != (expected["verdict"], expected["reason"]):
            problems.append(
                f"{key}: {row['verdict']} ({row['reason']}) instead of "
                f"{expected['verdict']} ({expected['reason']})")
            continue
        same_figures = (
            row["points"] == expected["points"]
            and abs((row["gain"] or 0) - (expected["gain"] or 0)) <= GAIN_TOLERANCE
        )
        if not same_figures and key not in KNOWN_GAPS:
            problems.append(
                f"{key}: same verdict, unexplained figures — points {row['points']} vs "
                f"{expected['points']}, gain {row['gain']} vs {expected['gain']}")
        if same_figures and key in KNOWN_GAPS:
            problems.append(f"{key}: listed in KNOWN_GAPS but no longer differs")
    assert not problems, "\n".join(problems)
    assert compared > 900


def test_the_only_new_rows_come_from_the_families_the_prototype_ignored(analyses, comparable):
    expected = _expected(load_rules(PATHS.rules))
    extra = {
        (country, row["canonical"]): row["family"]
        for country in comparable for row in analyses[country]["rows"]
        if (country, row["canonical"]) not in expected
    }

    assert set(extra.values()) <= NEW_FAMILIES, extra


def test_the_sources_are_those_of_the_specification_annex(analyses, comparable):
    def sources(country):
        return {source["path"].split("/")[-1]: set(source["families"]) - NEW_FAMILIES
                for source in analyses[country]["sources"]}

    annex = {
        # A family the newest file dropped keeps coming from the previous one.
        "AU": {"AU 1.5km 17.8.26 EXPERIMENTAL.json": {"car_year", "blur"},
               "Aus 13.04.26.json": {"copyright", "bl"}},
        "CA": {"Canada 17.08.26 - 2km.json": {"car_year"},
               "canada vit 09.04.26.json": {"copyright", "bl"}},
        "PE": {"Peru 30k (17.07.26).json": {"car_year", "copyright"},
               "pe 11k (02.05.26).json": {"bl"}},
        # Countries with no file of their own, served by a multi-country one.
        "BE": {"Europe Gen4 (27.11.25).json.zip": {"car_year"}},
        "PT": {"Europe Gen4 (27.11.25).json.zip": {"car_year"}},
        "LV": {"Baltics 70K (24.03.26).json": {"car_year", "copyright", "antenna"}},
        "US": {"us 850k 01.01.26.json.zip": {"car_year", "bl", "exposed"}},
        "ZA": {"za 30.04.26.json": {"copyright", "smallcam"}},
    }
    for country, expected in annex.items():
        if country in comparable:
            assert sources(country) == expected, country


def test_the_unused_files_are_the_superseded_ones(analyses, comparable):
    if len(comparable) < len(analyses):
        pytest.skip("the repository moved since the prototype")
    unused = {path.split("/")[-1] for path in unused_paths(mirror.load_state(PATHS), analyses)}

    assert unused == {
        "Spain 27.01.26 - 110K.json", "Ireland + Northern Ireland 27.01.26.json",
        "türkiye vit 05.04.26.json", "nz vit.json"}
