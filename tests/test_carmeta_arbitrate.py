import json

import pytest

from cartometa.carmeta.arbitrate import ArbitrationError, run_arbitrate
from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.rules import (
    LexiconEntry,
    Rules,
    analysis_fingerprint,
    load_rules,
    save_rules,
)

TODAY = "2026-11-20"


def _row(canonical, gain, verdict, reason="", key="Blue"):
    return {"canonical": canonical, "family": "car_year", "lexicon_key": key,
            "points": 500, "zones": 3, "capture": 0.9, "gain": gain,
            "verdict": verdict, "reason": reason,
            "rep": {"lat": 1.5, "lng": 2.5, "pano": "PANO", "heading": 10.0},
            "pieces": [{"kind": "clip"}]}


@pytest.fixture
def paths(tmp_path):
    paths = CarmetaPaths(tmp_path / "data")
    rules = Rules(lexicon={"Blue": LexiconEntry("Blue car")})
    save_rules(paths.rules, rules)
    paths.analysis_dir.mkdir(parents=True)
    for country, rows in {
        "LU": [_row("Blue 2024", 0.17, "arbitrage", "discriminance limite"),
               _row("Ford 2022", 0.50, "retenu", key="Ford"),
               _row("Blue 2023", 0.60, "retenu")],
        "ES": [_row("Blue 2024", 0.16, "arbitrage", "discriminance limite"),
               _row("Ford 2023", 0.15, "arbitrage", "discriminance limite", key="Ford")],
    }.items():
        paths.analysis(country).write_text(json.dumps({
            "country": country, "rules_fingerprint": analysis_fingerprint(rules),
            "sources": [], "rows": rows}), "utf-8")
    return paths


def _session(paths, answers):
    """Run with scripted answers; returns (decided, questions, printed text)."""
    answers = list(answers)
    questions, printed = [], []

    def ask(prompt):
        questions.append(prompt)
        if not answers:
            raise EOFError
        return answers.pop(0)

    decided = run_arbitrate(paths, ask, printed.append, today=TODAY)
    return decided, questions, "\n".join(printed)


def test_keep_and_drop_are_recorded_with_the_gain_and_the_date(paths):
    # Descriptor first (skipped here), then the tags in country order.
    decided, _, printed = _session(paths, ["s", "k", "d"])

    assert decided == 2
    rules = load_rules(paths.rules)
    assert {key: (d.decision, d.gain, d.decided_at) for key, d in rules.decisions.items()} == {
        "ES|Blue 2024": ("keep", 0.16, TODAY), "LU|Blue 2024": ("drop", 0.17, TODAY)}
    assert "ES  Blue 2024  -  500 points, 3 zone(s), 90% en zones, gain 16%" in printed
    assert "https://www.google.com/maps/@?api=1&map_action=pano&pano=PANO" in printed
    assert "2 décision(s) enregistrée(s), 1 cas encore en attente." in printed


def test_an_accepted_descriptor_asks_for_its_label_and_reveals_its_tags(paths):
    decided, questions, printed = _session(paths, ["k", "Ford car", "s", "k", "s"])

    rules = load_rules(paths.rules)
    assert rules.lexicon["Ford"] == LexiconEntry("Ford car", "accepted")
    assert "Descripteur inconnu : Ford  (2 tag(s))" in printed
    assert any("Libellé anglais" in question for question in questions)
    # `Ford 2023` in ES was hidden behind its descriptor: now a borderline case
    # of its own, asked in the same session (here: kept).
    assert rules.decisions["ES|Ford 2023"].decision == "keep"
    assert decided == 2


def test_an_empty_label_falls_back_on_the_key(paths):
    _session(paths, ["k", "", "q"])

    assert load_rules(paths.rules).lexicon["Ford"] == LexiconEntry("Ford", "accepted")


def test_a_dropped_descriptor_is_rejected_for_good(paths):
    _session(paths, ["d", "q"])

    assert load_rules(paths.rules).lexicon["Ford"].status == "rejected"
    _, _, printed = _session(paths, ["q"])
    assert "Ford" not in printed


def test_quitting_keeps_the_answers_already_given(paths):
    decided, _, _ = _session(paths, ["s", "k", "q"])

    assert decided == 1
    assert list(load_rules(paths.rules).decisions) == ["ES|Blue 2024"]


def test_running_out_of_input_is_a_clean_stop(paths):
    decided, _, printed = _session(paths, ["s", "k"])

    assert decided == 1 and "1 décision(s)" in printed


def test_an_unreadable_answer_is_asked_again(paths):
    decided, questions, printed = _session(paths, ["s", "maybe", "k", "q"])

    assert decided == 1 and "Réponse non comprise." in printed
    assert len(questions) == 4


def test_a_decided_case_is_not_asked_again_and_the_file_is_then_left_alone(paths):
    _session(paths, ["d", "k", "k"])
    before = paths.rules.read_bytes()

    decided, questions, printed = _session(paths, [])

    assert (decided, questions) == (0, [])
    assert "0 décision(s) enregistrée(s), 0 cas encore en attente." in printed
    assert paths.rules.read_bytes() == before


def test_arbitration_is_refused_on_an_analysis_made_under_other_rules(paths):
    rules = load_rules(paths.rules)
    rules.thresholds.gain_keep = 0.5
    save_rules(paths.rules, rules)

    with pytest.raises(ArbitrationError, match="sync --force"):
        _session(paths, ["k"])


def test_no_analysis_nothing_to_arbitrate(tmp_path):
    with pytest.raises(ArbitrationError, match="sync"):
        _session(CarmetaPaths(tmp_path / "data"), [])
