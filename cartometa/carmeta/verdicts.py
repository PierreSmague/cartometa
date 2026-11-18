"""Verdict of a tag: what the measures say, then what the maintainer decided.

Two layers, deliberately apart. The *geometric* verdict depends only on the
points and the thresholds: it is computed once and cached with the analysis.
The *effective* verdict adds the lexicon and the arbitration decisions, and is
recomputed every time the analysis is read — so that `arbitrate` then `import`
chain without re-running `sync`.
"""
from __future__ import annotations

from cartometa.carmeta.rules import (
    DECISION_DRIFT,
    DECISION_KEEP,
    LEXICON_ACCEPTED,
    LEXICON_REJECTED,
    Rules,
    Thresholds,
)

KEPT = "retenu"
ARBITRATION = "arbitrage"
DROPPED = "écarté"

REASON_PARENT = "couvert par des tags plus fins"
REASON_ISOLATED = "points surtout isolés"
REASON_FLAT = "non discriminant"
REASON_BORDERLINE = "discriminance limite"
REASON_UNKNOWN_WORD = "descripteur inconnu"
REASON_REJECTED_WORD = "descripteur écarté"
REASON_STALE = "décision à revoir"
REASON_DECIDED = "écarté par arbitrage"

KIND_DESCRIPTOR = "descriptor"
KIND_TAG = "tag"


def geometric_verdict(
    points: int, is_parent: bool, zones: int, capture: float, gain: float | None,
    thresholds: Thresholds,
) -> tuple[str, str]:
    """The first line of the specification's table that applies."""
    minimum = thresholds.min_zone_points
    if points < minimum:
        return DROPPED, f"moins de {minimum} points"
    if is_parent:
        return DROPPED, REASON_PARENT
    if zones == 0:
        return DROPPED, f"aucune zone de {minimum} points"
    if capture < thresholds.min_capture:
        return DROPPED, REASON_ISOLATED
    if gain < thresholds.gain_drop:
        return DROPPED, REASON_FLAT
    if gain < thresholds.gain_keep:
        return ARBITRATION, REASON_BORDERLINE
    return KEPT, ""


def reaches_gain(row: dict) -> bool:
    """True when only the gain lines of the table decided the row's fate.

    Those rows carry a footprint: they are the ones an arbitration decision
    can turn into a meta.
    """
    return row.get("pieces") is not None


def decision_key(country: str, canonical: str) -> str:
    # Country and canonical form, never the file path: the key must survive
    # the files being renamed from one version to the next.
    return f"{country}|{canonical}"


def effective_verdict(row: dict, country: str, rules: Rules) -> tuple[str, str]:
    if not reaches_gain(row):
        return row["verdict"], row["reason"]
    key = row.get("lexicon_key")
    if key is not None:
        entry = rules.lexicon.get(rules.lexicon_index.get(key.lower(), key))
        if entry is None or entry.status not in (LEXICON_ACCEPTED, LEXICON_REJECTED):
            return ARBITRATION, REASON_UNKNOWN_WORD
        if entry.status == LEXICON_REJECTED:
            return DROPPED, REASON_REJECTED_WORD
    decision = rules.decisions.get(decision_key(country, row["canonical"]))
    if decision is not None:
        # Asked again once the gain has moved by more than ten points, wherever
        # it now stands: the 10–20 % band is only ten points wide, so a stale
        # decision has necessarily left it, and handing over to the computed
        # verdict would import unasked a tag the maintainer had dropped.
        if (decision.gain is not None
                and abs(row["gain"] - decision.gain) > DECISION_DRIFT + 1e-9):
            return ARBITRATION, REASON_STALE
        if decision.decision == DECISION_KEEP:
            return KEPT, ""
        return DROPPED, REASON_DECIDED
    return row["verdict"], row["reason"]


def retained_rows(analysis: dict, rules: Rules) -> list[dict]:
    country = analysis["country"]
    return [row for row in analysis["rows"]
            if effective_verdict(row, country, rules)[0] == KEPT]


def pending_cases(analyses: dict[str, dict], rules: Rules) -> list[dict]:
    """What waits for the maintainer: unknown descriptors first, then tags.

    A descriptor is asked once for every tag and country that uses it; a tag
    is asked per country, because discriminance is a property of the country.
    """
    descriptors: dict[str, dict] = {}
    tags = []
    for country in sorted(analyses):
        for row in analyses[country]["rows"]:
            verdict, reason = effective_verdict(row, country, rules)
            if verdict != ARBITRATION:
                continue
            summary = {
                "country": country, "canonical": row["canonical"],
                "points": row["points"], "zones": row["zones"],
                "capture": row["capture"], "gain": row["gain"], "rep": row.get("rep"),
            }
            if reason == REASON_UNKNOWN_WORD:
                case = descriptors.setdefault(row["lexicon_key"], {
                    "kind": KIND_DESCRIPTOR, "key": row["lexicon_key"], "tags": [],
                })
                case["tags"].append(summary)
            else:
                tags.append({"kind": KIND_TAG, "reason": reason,
                             "key": decision_key(country, row["canonical"]), **summary})
    return [descriptors[key] for key in sorted(descriptors)] + tags
