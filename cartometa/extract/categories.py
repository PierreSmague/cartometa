from __future__ import annotations

# L'ordre compte : la première catégorie dont un mot-clé apparaît l'emporte.
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("bollards", ("bollard",)),
    ("poteaux", ("pole", "poles", "utility pole", "power line", "pylon")),
    ("vehicule", ("google car", "camera", "rift", "snorkel", "car blur", "subaru")),
    ("vegetation", ("orchard", "forest", "tree", "trees", "vegetation", "crop", "field")),
    ("signalisation", ("sign", "signs", "signal", "marking", "road line", "chevron", "guardrail")),
]


def infer_category(title: str, description: str) -> str:
    for haystack in (title.lower(), description.lower()):
        for category, words in KEYWORDS:
            if any(word in haystack for word in words):
                return category
    return "autre"
