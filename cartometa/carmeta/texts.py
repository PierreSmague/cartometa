"""What a carmeta meta says: its id, title, description and Street View link.

Sentence templates live here, wordings in the lexicon of rules.json — that is
where a wrong label is corrected, never in the generated files.
"""
from __future__ import annotations

import hashlib
from urllib.parse import urlencode

from cartometa.carmeta.rules import LexiconEntry, Rules
from cartometa.carmeta.tags import FAMILY_CAR_YEAR, FAMILY_COPYRIGHT

SOURCE_URL = "https://github.com/iggedi-ig-ig/carmeta"
ID_PREFIX = "car-"

_ANTENNA_TITLE = {"A": ", antenna", "NA": ", no antenna"}
_ANTENNA_PHRASE = {"A": ", antenna visible", "NA": ", no antenna visible"}


def meta_id(country: str, canonical: str) -> str:
    """Deterministic, and blind to the file: stable from one version of a file
    to the next and from one spelling of the tag to another."""
    digest = hashlib.sha1(f"{country}|{canonical}".encode("utf-8")).hexdigest()
    return f"{ID_PREFIX}{digest[:6]}"


def _entry(row: dict, rules: Rules) -> LexiconEntry:
    key = row["lexicon_key"]
    found = rules.lexicon.get(rules.lexicon_index.get(key.lower(), key))
    return found if found is not None else LexiconEntry(label=key)


def title(row: dict, rules: Rules) -> str:
    if row["family"] == FAMILY_COPYRIGHT:
        return f"©{row['year']} copyright"
    label = _entry(row, rules).label
    if row["family"] == FAMILY_CAR_YEAR:
        # `(A+NA)` says nothing more than no suffix at all.
        return f"{label}{_ANTENNA_TITLE.get(row.get('antenna'), '')} · {row['year']}"
    return label


def description(row: dict, rules: Rules, points: int) -> str:
    footprint = f"Footprint computed from {points:,} locations tagged by carmeta."
    if row["family"] == FAMILY_COPYRIGHT:
        return (f"Street View coverage carrying the ©{row['year']} Google copyright. "
                f"{footprint}")
    entry = _entry(row, rules)
    if row["family"] == FAMILY_CAR_YEAR:
        phrase = entry.phrase or f"shot with the {entry.label.lower()}"
        antenna = _ANTENNA_PHRASE.get(row.get("antenna"), "")
        return (f"Street View coverage from {row['year']} {phrase}{antenna}. "
                f"{footprint}")
    phrase = entry.phrase or f"showing: {entry.label.lower()}"
    return f"Street View coverage {phrase}. {footprint}"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(round(float(value), 1))


def maps_url(rep: dict, pitch: float) -> str:
    """One link to a representative panorama, looking down at the car."""
    return "https://www.google.com/maps/@?" + urlencode({
        "api": 1, "map_action": "pano", "pano": rep["pano"],
        "viewpoint": f"{rep['lat']},{rep['lng']}",
        "heading": _number(rep.get("heading") or 0.0),
        "pitch": _number(pitch),
    })
