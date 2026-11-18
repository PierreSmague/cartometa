from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

FAMILY_CAR_YEAR = "car_year"
FAMILY_CAR = "car"
FAMILY_COPYRIGHT = "copyright"
FAMILY_UNKNOWN = "unknown"

# The families a meta can come from. Everything else `classify` recognises
# (years, months, weather, country codes...) is dropped on sight.
KEPT_FAMILIES = (
    FAMILY_CAR_YEAR, FAMILY_CAR, FAMILY_COPYRIGHT, "antenna", "bl", "blur",
    "exposed", "snow", "smallcam", FAMILY_UNKNOWN,
)

_SEPARATOR = re.compile(r"[─—═]{3,}")
_COPYRIGHT = re.compile(r"©\s?(\d{4})")
_YEAR = re.compile(r"(19|20)\d{2}")
_MONTH = re.compile(r"[1-9]|1[0-2]")
_YEARMONTH = re.compile(r"\d\d-\d\d")
_KOPPEN = re.compile(
    r"Af|Am|Aw|As|BW[hk]|BS[hk]|C[sfw][abc]|D[sfw][abcd]|ET|EF")
_PARTS = re.compile(r"P\d+|Part \d+")
_COUNTRY = re.compile(r"[A-Z]{2}")
_CAR_YEAR = re.compile(
    r"(?P<desc>.+?)\s+(?P<year>20\d{2}|\d{2})"
    r"(?:\s*\((?P<ant>A|NA|A\s*\+\s*NA)\))?")

_WEATHER = frozenset({"clear", "some clouds", "overcast"})
# Subdivisions used as tags: the 16 German Länder today.
_ADMIN = frozenset({
    "bayern", "niedersachsen", "nordrhein-westfalen", "baden-württemberg",
    "brandenburg", "mecklenburg-vorpommern", "rheinland-pfalz", "sachsen-anhalt",
    "sachsen", "schleswig-holstein", "thüringen", "hessen", "berlin", "saarland",
    "hamburg", "bremen",
})
_CAMERA_GEN = frozenset({"gen 4", "normal gen 4"})
# Standalone clues: lowercase spelling in the files -> (family, canonical text).
# `BL` and `Brakelight` are the same clue (backlight / brake light).
_STANDALONE = {
    "bl": ("bl", "BL"),
    "brakelight": ("bl", "BL"),
    "smallcam": ("smallcam", "Smallcam"),
    "antenna": ("antenna", "Antenna"),
    "front blur": ("blur", "Front Blur"),
    "new blur": ("blur", "New Blur"),
    "exposed": ("exposed", "Exposed"),
    "exposed back": ("exposed", "Exposed Back"),
    "snow": ("snow", "Snow"),
}
# Kept as it is: the car is invisible, and that IS the meta.
_NO_CAR = "no car"


@dataclass(frozen=True)
class Canonical:
    """A raw tag reduced to the form two files agree on."""

    family: str
    text: str
    # What the lexicon is asked about: the descriptor of a car tag, the whole
    # text of a standalone clue. None for a copyright, which needs no wording.
    lexicon_key: str | None
    year: int | None = None
    antenna: str | None = None


def _squeeze(text: str) -> str:
    return " ".join(text.split())


def normalize_descriptor(descriptor: str) -> str:
    """`Blue Car Antenna` -> `Blue`, `Grey` -> `Gray`; `No Car` stays itself."""
    words = _squeeze(descriptor).split(" ")
    words = ["Gray" if w.lower() == "grey" else w for w in words]
    if " ".join(words).lower() == _NO_CAR:
        return "No Car"
    kept = [w for w in words if w.lower() not in ("car", "antenna")]
    if " ".join(kept).lower() == "no":
        # `No Car Antenna 2024`: still the invisible car.
        return "No Car"
    # A descriptor made of nothing but the dropped words keeps them: an empty
    # descriptor would merge unrelated tags under one empty key.
    return " ".join(kept) if kept else " ".join(words)


def _spelled(text: str, lexicon_index: Mapping[str, str]) -> str:
    """The lexicon's own spelling of `text` when it knows it."""
    return lexicon_index.get(text.lower(), text)


def classify(
    tag: str, iso_codes: frozenset[str], lexicon_index: Mapping[str, str]
) -> Canonical | None:
    """The canonical form of a raw tag, or None when its family is dropped.

    The order of the tests is the order of the specification's table, and it
    matters: `BL` is two capitals and would pass for a country code.
    `lexicon_index` maps lowercase keys to the lexicon's spelling.
    """
    text = _squeeze(tag)
    low = text.lower()
    if not text or _SEPARATOR.search(text):
        return None
    match = _COPYRIGHT.fullmatch(text)
    if match:
        year = int(match.group(1))
        return Canonical(FAMILY_COPYRIGHT, f"©{year}", None, year=year)
    if _YEAR.fullmatch(text) or _MONTH.fullmatch(text) or _YEARMONTH.fullmatch(text):
        return None
    if low in _WEATHER or _KOPPEN.fullmatch(text) or _PARTS.fullmatch(text):
        return None
    if low in ("bl", "brakelight"):
        return Canonical("bl", "BL", "BL")
    # Every `No …` is the absence of a clue — except the invisible car.
    if low.startswith("no ") and not low.startswith(_NO_CAR):
        return None
    if _COUNTRY.fullmatch(text) and text in iso_codes:
        return None
    if low in _ADMIN or low in _CAMERA_GEN:
        return None
    if low in _STANDALONE:
        family, canonical = _STANDALONE[low]
        return Canonical(family, canonical, canonical)
    match = _CAR_YEAR.fullmatch(text)
    if match:
        raw = match.group("desc")
        descriptor = _spelled(normalize_descriptor(raw), lexicon_index)
        digits = match.group("year")
        year = int(digits) if len(digits) == 4 else 2000 + int(digits)
        antenna = match.group("ant")
        if antenna:
            antenna = antenna.replace(" ", "")
        elif any(word.lower() == "antenna" for word in raw.split()):
            antenna = "A"
        suffix = f" ({antenna})" if antenna else ""
        return Canonical(FAMILY_CAR_YEAR, f"{descriptor} {year}{suffix}",
                         descriptor, year=year, antenna=antenna)
    descriptor = normalize_descriptor(text)
    if descriptor.lower() in lexicon_index:
        key = lexicon_index[descriptor.lower()]
        return Canonical(FAMILY_CAR, key, key)
    return Canonical(FAMILY_UNKNOWN, text, text)
