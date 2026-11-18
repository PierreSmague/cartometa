from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cartometa.atomic_write import write_json_atomic

LEXICON_ACCEPTED = "accepted"
LEXICON_PENDING = "pending"
LEXICON_REJECTED = "rejected"
LEXICON_STATUSES = (LEXICON_ACCEPTED, LEXICON_PENDING, LEXICON_REJECTED)

DECISION_KEEP = "keep"
DECISION_DROP = "drop"
DECISIONS = (DECISION_KEEP, DECISION_DROP)

# A decision is asked again once the gain has drifted this far from the gain
# it was taken on. Not a threshold of rules.json: it qualifies the decisions
# themselves, and changing it must not invalidate the cached analysis.
DECISION_DRIFT = 0.10

DEFAULT_PITCH = -35.0


class RulesError(ValueError):
    """rules.json is unreadable or carries a value nothing knows how to apply."""


@dataclass
class Thresholds:
    min_zone_points: int = 30
    min_capture: float = 0.35
    gain_drop: float = 0.10
    gain_keep: float = 0.20
    reproposal_iou: float = 0.80


@dataclass
class LexiconEntry:
    label: str
    status: str = LEXICON_ACCEPTED
    # What follows "Street View coverage [from <year>] " in the generated
    # description. Optional: without it the sentence is built from the label.
    phrase: str | None = None


@dataclass
class Decision:
    decision: str
    gain: float | None
    decided_at: str


@dataclass
class Rules:
    thresholds: Thresholds = field(default_factory=Thresholds)
    pin: dict[str, str] = field(default_factory=dict)
    exclude: list[str] = field(default_factory=list)
    lexicon: dict[str, LexiconEntry] = field(default_factory=dict)
    decisions: dict[str, Decision] = field(default_factory=dict)
    streetview_pitch: float = DEFAULT_PITCH

    @property
    def lexicon_index(self) -> dict[str, str]:
        """Lowercase key -> key as the lexicon spells it.

        The files do not agree on case (`smallcam`, `Smallcam`): the lookup is
        case-insensitive and the lexicon's spelling wins.
        """
        return {key.lower(): key for key in self.lexicon}

    def to_dict(self) -> dict:
        payload = {
            "thresholds": asdict(self.thresholds),
            "sources": {"pin": dict(sorted(self.pin.items())),
                        "exclude": sorted(self.exclude)},
            "lexicon": {
                key: {k: v for k, v in asdict(entry).items() if v is not None}
                for key, entry in sorted(self.lexicon.items())
            },
            "decisions": {
                key: asdict(decision)
                for key, decision in sorted(self.decisions.items())
            },
        }
        # Absent rather than written at its default: the file stays what the
        # maintainer typed.
        if self.streetview_pitch != DEFAULT_PITCH:
            payload["streetview_pitch"] = self.streetview_pitch
        return payload


_TOP_LEVEL = {"thresholds", "sources", "lexicon", "decisions", "streetview_pitch"}


def _unknown(where: str, given, known) -> None:
    extra = sorted(set(given) - set(known))
    if extra:
        raise RulesError(f"rules.json: unknown key(s) in {where}: {', '.join(extra)}")


def rules_from_dict(payload: dict) -> Rules:
    if not isinstance(payload, dict):
        raise RulesError("rules.json: the top level must be an object")
    _unknown("the top level", payload, _TOP_LEVEL)
    raw_thresholds = payload.get("thresholds", {})
    _unknown("thresholds", raw_thresholds, asdict(Thresholds()))
    sources = payload.get("sources", {})
    _unknown("sources", sources, {"pin", "exclude"})
    lexicon = {}
    for key, raw in payload.get("lexicon", {}).items():
        _unknown(f"lexicon[{key!r}]", raw, {"label", "status", "phrase"})
        entry = LexiconEntry(label=raw.get("label", key),
                             status=raw.get("status", LEXICON_ACCEPTED),
                             phrase=raw.get("phrase"))
        if entry.status not in LEXICON_STATUSES:
            raise RulesError(
                f"rules.json: lexicon[{key!r}] has status {entry.status!r} "
                f"(expected {', '.join(LEXICON_STATUSES)})")
        lexicon[key] = entry
    decisions = {}
    for key, raw in payload.get("decisions", {}).items():
        _unknown(f"decisions[{key!r}]", raw, {"decision", "gain", "decided_at"})
        decision = Decision(decision=raw.get("decision", ""), gain=raw.get("gain"),
                            decided_at=raw.get("decided_at", ""))
        if decision.decision not in DECISIONS:
            raise RulesError(
                f"rules.json: decisions[{key!r}] is {decision.decision!r} "
                f"(expected {' or '.join(DECISIONS)})")
        decisions[key] = decision
    return Rules(
        thresholds=Thresholds(**raw_thresholds),
        pin=dict(sources.get("pin", {})),
        exclude=list(sources.get("exclude", [])),
        lexicon=lexicon,
        decisions=decisions,
        streetview_pitch=float(payload.get("streetview_pitch", DEFAULT_PITCH)),
    )


def load_rules(path: Path) -> Rules:
    """The rules, or the defaults when the file does not exist yet."""
    if not path.exists():
        return Rules()
    try:
        payload = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise RulesError(f"{path}: unreadable JSON ({exc})") from None
    return rules_from_dict(payload)


def save_rules(path: Path, rules: Rules) -> None:
    write_json_atomic(path, rules.to_dict())


def analysis_fingerprint(rules: Rules) -> str:
    """What the cached analysis depends on: thresholds and source overrides.

    Decisions and lexicon are applied when the analysis is read, so that
    `arbitrate` then `import` chain without a `sync` in between; they are
    deliberately left out. So is `reproposal_iou`, which only the import reads.
    """
    thresholds = asdict(rules.thresholds)
    thresholds.pop("reproposal_iou")
    payload = {"thresholds": thresholds,
               "pin": dict(sorted(rules.pin.items())),
               "exclude": sorted(rules.exclude)}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
