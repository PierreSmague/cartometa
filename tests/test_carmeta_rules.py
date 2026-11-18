import json
from pathlib import Path

import pytest

from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.rules import (
    Decision,
    LexiconEntry,
    Rules,
    RulesError,
    analysis_fingerprint,
    load_rules,
    save_rules,
)

VERSIONED = Path(__file__).resolve().parents[1] / "data" / "carmeta" / "rules.json"


def test_a_missing_file_gives_the_default_thresholds(tmp_path):
    rules = load_rules(tmp_path / "rules.json")

    assert rules.thresholds.min_zone_points == 30
    assert rules.thresholds.min_capture == 0.35
    assert (rules.thresholds.gain_drop, rules.thresholds.gain_keep) == (0.10, 0.20)
    assert rules.thresholds.reproposal_iou == 0.80
    assert rules.lexicon == {} and rules.decisions == {}


def test_saving_then_loading_is_byte_stable(tmp_path):
    path = tmp_path / "rules.json"
    rules = Rules()
    rules.pin["AU|copyright"] = "Oceania/Aus.json"
    rules.exclude.append("Europe/old.json")
    rules.lexicon["Ford"] = LexiconEntry("Ford", "pending")
    rules.lexicon["Blue"] = LexiconEntry("Blue car", "accepted", "shot with the blue car")
    rules.decisions["LU|Blue 2024"] = Decision("keep", 0.17, "2026-11-20")
    save_rules(path, rules)
    first = path.read_bytes()

    save_rules(path, load_rules(path))

    assert path.read_bytes() == first
    assert load_rules(path) == rules


def test_the_versioned_rules_file_loads_and_is_canonical(tmp_path):
    rules = load_rules(VERSIONED)

    # Only what arbitration never changes is asserted: statuses and decisions
    # in this file are the maintainer's, and move.
    assert rules.lexicon["Blue"].label == "Blue car"
    assert rules.lexicon["Blue"].status == "accepted"
    # `Alberta Car` of the specification's annex, through the normaliser.
    assert "Alberta" in rules.lexicon and "Alberta Car" not in rules.lexicon
    copy = tmp_path / "rules.json"
    save_rules(copy, rules)
    assert copy.read_bytes() == VERSIONED.read_bytes()


@pytest.mark.parametrize("payload, needle", [
    ({"thresholds": {"min_zone": 3}}, "min_zone"),
    ({"seuils": {}}, "seuils"),
    ({"lexicon": {"Blue": {"label": "Blue car", "status": "maybe"}}}, "maybe"),
    ({"decisions": {"LU|Blue 2024": {"decision": "yes"}}}, "yes"),
])
def test_an_unknown_key_or_value_is_named(tmp_path, payload, needle):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(payload), "utf-8")

    with pytest.raises(RulesError, match=needle):
        load_rules(path)


def test_the_fingerprint_follows_thresholds_and_sources_only():
    base = analysis_fingerprint(Rules())

    with_threshold = Rules()
    with_threshold.thresholds.gain_keep = 0.25
    with_pin = Rules()
    with_pin.pin["AU"] = "Oceania/Aus.json"
    with_exclusion = Rules()
    with_exclusion.exclude.append("Europe/old.json")
    assert len({base, analysis_fingerprint(with_threshold),
                analysis_fingerprint(with_pin),
                analysis_fingerprint(with_exclusion)}) == 4

    # Applied when the analysis is read, never baked into it.
    unrelated = Rules()
    unrelated.decisions["LU|Blue 2024"] = Decision("keep", 0.17, "2026-11-20")
    unrelated.lexicon["Ford"] = LexiconEntry("Ford", "pending")
    unrelated.thresholds.reproposal_iou = 0.5
    assert analysis_fingerprint(unrelated) == base


def test_the_lexicon_index_is_case_insensitive():
    rules = Rules(lexicon={"Smallcam": LexiconEntry("Smallcam")})

    assert rules.lexicon_index["smallcam"] == "Smallcam"


def test_the_paths_keep_cache_and_versioned_data_apart(tmp_path):
    paths = CarmetaPaths(tmp_path / "data")

    for cached in (paths.files, paths.state, paths.analysis("MX"), paths.report,
                   paths.pending, paths.lock, paths.compact("abc")):
        assert cached.is_relative_to(paths.cache)
    assert not paths.rules.is_relative_to(paths.cache)
    assert paths.metas("MX") == tmp_path / "data" / "carmeta" / "MX.json"
