"""`cartometa-carmeta arbitrate`: settle the filter's borderline cases, once.

Every answer goes straight into the versioned rules.json: a decision is
durable, and quitting halfway loses nothing.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date

from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.rules import (
    DECISION_DROP,
    DECISION_KEEP,
    LEXICON_ACCEPTED,
    LEXICON_REJECTED,
    Decision,
    LexiconEntry,
    Rules,
    analysis_fingerprint,
    load_rules,
    save_rules,
)
from cartometa.carmeta.sync import load_analyses
from cartometa.carmeta.texts import maps_url
from cartometa.carmeta.verdicts import KIND_DESCRIPTOR, pending_cases

KEEP, DROP, SKIP, QUIT = "k", "d", "s", "q"
PROMPT = "[k] garder  [d] écarter  [s] passer  [q] quitter > "
# Tags shown under an unknown descriptor: enough to judge, not a full listing.
SHOWN_TAGS = 5


class ArbitrationError(ValueError):
    """Nothing can be arbitrated in the current state of the cache."""


def checked_analyses(paths: CarmetaPaths, rules: Rules) -> dict[str, dict]:
    """The cached analyses, refused when the rules they were made with moved.

    A decision records the gain it was taken on: taking it on figures computed
    under other thresholds would date it wrongly from the start.
    """
    analyses = load_analyses(paths)
    if not analyses:
        raise ArbitrationError(
            "aucune analyse en cache : lancer `cartometa-carmeta sync` d'abord.")
    fingerprint = analysis_fingerprint(rules)
    stale = sorted(code for code, analysis in analyses.items()
                   if analysis.get("rules_fingerprint") != fingerprint)
    if stale:
        raise ArbitrationError(
            f"l'analyse en cache ({', '.join(stale)}) a été faite avec d'autres seuils "
            f"ou d'autres sources que rules.json. Lancer `cartometa-carmeta sync --force`.")
    return analyses


def _figures(tag: dict) -> str:
    return (f"{tag['country']}  {tag['canonical']}  -  {tag['points']} points, "
            f"{tag['zones']} zone(s), {tag['capture']:.0%} en zones, gain {tag['gain']:.0%}")


def _link(tag: dict, rules: Rules) -> str:
    return f"    {maps_url(tag['rep'], rules.streetview_pitch)}" if tag.get("rep") else ""


def _show(case: dict, rules: Rules, out: Callable[[str], None]) -> None:
    out("")
    if case["kind"] == KIND_DESCRIPTOR:
        tags = sorted(case["tags"], key=lambda tag: -tag["points"])
        out(f"Descripteur inconnu : {case['key']}  ({len(tags)} tag(s))")
        for tag in tags[:SHOWN_TAGS]:
            out(f"  {_figures(tag)}")
            if _link(tag, rules):
                out(_link(tag, rules))
        if len(tags) > SHOWN_TAGS:
            out(f"  … et {len(tags) - SHOWN_TAGS} autre(s)")
        return
    out(f"{_figures(case)}  ({case['reason']})")
    if _link(case, rules):
        out(_link(case, rules))


def run_arbitrate(paths: CarmetaPaths, ask: Callable[[str], str],
                  out: Callable[[str], None], today: str | None = None) -> int:
    """Walk the pending cases; returns how many were decided.

    Unknown descriptors come first: accepting one can turn its tags into
    borderline cases of their own, which then show up in the same session.
    """
    rules = load_rules(paths.rules)
    analyses = checked_analyses(paths, rules)
    today = today or date.today().isoformat()
    skipped: set[tuple[str, str]] = set()
    decided = 0
    while True:
        cases = [case for case in pending_cases(analyses, rules)
                 if (case["kind"], case["key"]) not in skipped]
        if not cases:
            break
        case = cases[0]
        _show(case, rules, out)
        try:
            answer = ask(PROMPT).strip().lower()
        except EOFError:
            answer = QUIT
        if answer == QUIT:
            break
        if answer == SKIP:
            skipped.add((case["kind"], case["key"]))
            continue
        if answer not in (KEEP, DROP):
            out("Réponse non comprise.")
            continue
        if case["kind"] == KIND_DESCRIPTOR:
            key = case["key"]
            if answer == KEEP:
                try:
                    label = ask(f"Libellé anglais pour le titre [{key}] > ").strip()
                except EOFError:
                    break
                rules.lexicon[key] = LexiconEntry(label or key, LEXICON_ACCEPTED)
            else:
                rules.lexicon[key] = LexiconEntry(key, LEXICON_REJECTED)
        else:
            rules.decisions[case["key"]] = Decision(
                DECISION_KEEP if answer == KEEP else DECISION_DROP, case["gain"], today)
        # After every answer: a decision is never lost to a Ctrl-C.
        save_rules(paths.rules, rules)
        decided += 1
    remaining = len(pending_cases(analyses, rules))
    out("")
    out(f"{decided} décision(s) enregistrée(s), {remaining} cas encore en attente.")
    return decided
