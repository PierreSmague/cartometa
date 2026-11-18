import pytest

from cartometa.carmeta.rules import Decision, LexiconEntry, Rules, Thresholds
from cartometa.carmeta.verdicts import (
    effective_verdict,
    geometric_verdict,
    pending_cases,
    retained_rows,
)


def _row(canonical="Blue 2024", gain=0.17, verdict="arbitrage",
         reason="discriminance limite", key="Blue", pieces=True, points=500):
    return {"canonical": canonical, "family": "car_year", "lexicon_key": key,
            "points": points, "zones": 3, "capture": 0.9, "gain": gain,
            "verdict": verdict, "reason": reason, "rep": {"pano": "p"},
            "pieces": [{"kind": "clip"}] if pieces else None}


def _rules(**decisions):
    return Rules(
        lexicon={"Blue": LexiconEntry("Blue car"),
                 "Ford": LexiconEntry("Ford", "pending"),
                 "Truck": LexiconEntry("Truck", "rejected")},
        decisions={key.replace("_", "|", 1): Decision(what, gain, "2026-11-20")
                   for key, (what, gain) in decisions.items()},
    )


@pytest.mark.parametrize("args, expected", [
    ((29, False, 0, 0.0, None), ("écarté", "moins de 30 points")),
    ((500, True, 3, 0.9, 0.5), ("écarté", "couvert par des tags plus fins")),
    ((500, False, 0, 0.0, None), ("écarté", "aucune zone de 30 points")),
    ((500, False, 2, 0.34, 0.5), ("écarté", "points surtout isolés")),
    ((500, False, 2, 0.35, 0.099), ("écarté", "non discriminant")),
    ((500, False, 2, 0.9, 0.10), ("arbitrage", "discriminance limite")),
    ((500, False, 2, 0.9, 0.199), ("arbitrage", "discriminance limite")),
    ((500, False, 2, 0.9, 0.20), ("retenu", "")),
])
def test_the_first_matching_line_of_the_table_wins(args, expected):
    assert geometric_verdict(*args, Thresholds()) == expected


def test_without_a_decision_the_geometric_verdict_stands():
    assert effective_verdict(_row(), "LU", _rules()) == ("arbitrage", "discriminance limite")
    assert effective_verdict(_row(gain=0.4, verdict="retenu", reason=""), "LU",
                             _rules()) == ("retenu", "")


def test_a_keep_decision_retains_and_a_drop_decision_drops():
    assert effective_verdict(_row(), "LU", _rules(**{"LU_Blue 2024": ("keep", 0.17)})) == (
        "retenu", "")
    assert effective_verdict(_row(), "LU", _rules(**{"LU_Blue 2024": ("drop", 0.17)})) == (
        "écarté", "écarté par arbitrage")


def test_a_decision_belongs_to_one_country():
    rules = _rules(**{"LU_Blue 2024": ("keep", 0.17)})

    assert effective_verdict(_row(), "ES", rules)[0] == "arbitrage"


def test_a_decision_holds_while_the_gain_stays_within_ten_points():
    rules = _rules(**{"LU_Blue 2024": ("drop", 0.17)})
    risen = _row(gain=0.22, verdict="retenu", reason="")

    # The computed verdict would retain it; the maintainer said no, and that holds.
    assert effective_verdict(risen, "LU", rules) == ("écarté", "écarté par arbitrage")

    kept = _rules(**{"LU_Blue 2024": ("keep", 0.17)})
    fallen = _row(gain=0.08, verdict="écarté", reason="non discriminant")
    assert effective_verdict(fallen, "LU", kept) == ("retenu", "")


@pytest.mark.parametrize("what, decided, now, computed", [
    ("drop", 0.12, 0.40, ("retenu", "")),
    ("keep", 0.17, 0.05, ("écarté", "non discriminant")),
])
def test_a_decision_is_asked_again_once_the_gain_has_moved_too_far(what, decided, now, computed):
    rules = _rules(**{"LU_Blue 2024": (what, decided)})
    row = _row(gain=now, verdict=computed[0], reason=computed[1])

    assert effective_verdict(row, "LU", rules) == ("arbitrage", "décision à revoir")


def test_an_unknown_or_pending_descriptor_waits_whatever_the_gain():
    rules = _rules(**{"LU_Ford 2022": ("keep", 0.5)})
    strong = dict(gain=0.5, verdict="retenu", reason="")

    assert effective_verdict(_row("Ford 2022", key="Ford", **strong), "LU", rules) == (
        "arbitrage", "descripteur inconnu")
    assert effective_verdict(_row("Zorglub", key="Zorglub", **strong), "LU", rules) == (
        "arbitrage", "descripteur inconnu")


def test_a_rejected_descriptor_is_dropped_for_good():
    row = _row("Truck 2024", key="Truck", gain=0.5, verdict="retenu", reason="")

    assert effective_verdict(row, "LU", _rules()) == ("écarté", "descripteur écarté")


def test_the_lexicon_is_looked_up_without_regard_to_case():
    row = _row("blue 2024", key="blue", gain=0.5, verdict="retenu", reason="")

    assert effective_verdict(row, "LU", _rules()) == ("retenu", "")


def test_a_copyright_needs_no_descriptor():
    row = _row("©2025", key=None, gain=0.5, verdict="retenu", reason="")

    assert effective_verdict(row, "LU", _rules()) == ("retenu", "")


def test_a_row_dropped_before_the_gain_lines_is_beyond_any_decision():
    row = _row("Ford 2022", key="Ford", pieces=False, verdict="écarté",
               reason="points surtout isolés")
    rules = _rules(**{"LU_Ford 2022": ("keep", 0.17)})

    assert effective_verdict(row, "LU", rules) == ("écarté", "points surtout isolés")


def _analyses():
    return {
        "LU": {"country": "LU", "rows": [
            _row("Blue 2024"),                                              # borderline
            _row("Blue 2023", gain=0.5, verdict="retenu", reason=""),
            _row("Ford 2022", key="Ford", gain=0.5, verdict="retenu", reason=""),
            _row("Truck 2024", key="Truck", gain=0.5, verdict="retenu", reason=""),
            _row("Blue 2020", pieces=False, verdict="écarté", reason="moins de 30 points"),
        ]},
        "ES": {"country": "ES", "rows": [
            _row("Ford 2023", key="Ford", gain=0.3, verdict="retenu", reason=""),
            _row("Blue 2024", gain=0.16),
        ]},
    }


def test_pending_cases_list_descriptors_first_then_tags():
    cases = pending_cases(_analyses(), _rules())

    assert [(c["kind"], c["key"]) for c in cases] == [
        ("descriptor", "Ford"), ("tag", "ES|Blue 2024"), ("tag", "LU|Blue 2024")]
    assert [(t["country"], t["canonical"]) for t in cases[0]["tags"]] == [
        ("ES", "Ford 2023"), ("LU", "Ford 2022")]
    assert cases[1]["gain"] == 0.16 and cases[1]["reason"] == "discriminance limite"


def test_a_decided_case_is_no_longer_pending():
    rules = _rules(**{"LU_Blue 2024": ("keep", 0.17), "ES_Blue 2024": ("drop", 0.16)})
    rules.lexicon["Ford"] = LexiconEntry("Ford", "accepted")

    assert pending_cases(_analyses(), rules) == []
    assert [r["canonical"] for r in retained_rows(_analyses()["LU"], rules)] == [
        "Blue 2024", "Blue 2023", "Ford 2022"]
    assert [r["canonical"] for r in retained_rows(_analyses()["ES"], rules)] == ["Ford 2023"]
