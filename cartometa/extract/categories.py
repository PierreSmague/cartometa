from __future__ import annotations
import re

# L'ordre compte : la première catégorie dont un mot-clé apparaît l'emporte.
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("bollards", ("bollard",)),
    ("poteaux", ("pole", "poles", "utility pole", "power line", "pylon")),
    ("vehicule", ("google car", "camera", "rift", "snorkel", "car blur", "subaru")),
    ("vegetation", ("orchard", "forest", "tree", "trees", "vegetation", "crop", "field")),
    ("signalisation", ("sign", "signs", "signal", "marking", "road line", "chevron", "guardrail")),
]

# Chaque mot-clé (simple ou expression à plusieurs mots) est recherché à
# partir d'une limite de mot, pour éviter les faux positifs de sous-chaîne
# au milieu d'un autre mot (ex. "tree" dans "street") tout en acceptant les
# suffixes flexionnels (ex. "orchard" reconnu dans "orchards").
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
