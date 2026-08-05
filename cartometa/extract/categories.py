from __future__ import annotations
import re

# Order matters: the first category one of whose keywords appears wins.
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("bollards", ("bollard",)),
    ("poteaux", ("pole", "poles", "utility pole", "power line", "pylon")),
    ("vehicule", ("google car", "camera", "rift", "snorkel", "car blur", "subaru")),
    ("vegetation", ("orchard", "forest", "tree", "trees", "vegetation", "crop", "field")),
    ("signalisation", ("sign", "signs", "signal", "marking", "road line", "chevron", "guardrail")),
]

# Each keyword (single word or multi-word phrase) is searched for from a word
# boundary, to avoid substring false positives in the middle of another word
# (e.g. "tree" inside "street") while still accepting inflectional suffixes
# (e.g. "orchard" recognised inside "orchards").
_WORD_RE_CACHE: dict[str, re.Pattern[str]] = {
    word: re.compile(r"\b" + re.escape(word))
    for _, words in KEYWORDS
    for word in words
}


def infer_category(title: str, description: str) -> str:
    for haystack in (title.lower(), description.lower()):
        for category, words in KEYWORDS:
            if any(_WORD_RE_CACHE[word].search(haystack) for word in words):
                return category
    return "autre"
