from __future__ import annotations
import re

# Display order: the order of the filter pills on the site and of the options in
# the review form. `tests/test_build_dataset.py` pins the site against it.
CATEGORIES: tuple[str, ...] = (
    "infrastructure",
    "vegetation",
    "landscape",
    "architecture",
    "car",
    "culture",
    "autre",
)

# Kept as `autre` rather than `other`: it is the stored value for 2435 metas and
# for 21 versioned manual ones. Renaming it would migrate the majority of the
# corpus for a cosmetic gain.
FALLBACK = "autre"

# The one exception to object-wins. When the clue is a writing system or a
# language, the meta is Culture even though the player is looking at a sign.
#
# Evaluated over title AND description together, before every other rule:
# `infer_category` resolves the title completely before reading the description,
# so "Direction signs" / "written in Cyrillic" would otherwise come out as
# infrastructure.
#
# `latin` and `arabic` are never accepted bare — "Latin America" and "Arabic
# peninsula" are places, not scripts.
LANGUAGE = (
    r"\b(cyrillic|glagolitic|kanji|kana|hangul|hanzi|devanagari|abjad"
    r"|(?:latin|arabic|greek|hebrew|thai|khmer|georgian|armenian)\s"
    r"(?:script|alphabet|letters?|characters?|numerals?)"
    r"|script|alphabet|lettering|diacritic|umlaut|tilde|cedilla"
    r"|language|bilingual|transliterat|spelling)"
)

# Object-wins rules, first match wins, evaluated on the title then on the
# description.
#
# DO NOT REORDER TO FIX ONE META. The order decides hundreds of others: "a road
# winds through the mountains" is infrastructure because the road matches first.
# Add an entry to data/categories.json instead.
RULES: list[tuple[str, str]] = [
    # The vehicle and the capture itself. Bare `car` is deliberately excluded:
    # it would swallow "car park". A colour or an article in front of it is what
    # marks the Google car.
    ("car", r"\b(google car|street ?view car|(?:the|a|white|blue|grey|gray|black|red)\s"
            r"cars?\b|vehicle|camera|antenna|blur|rift|snorkel|trekker|coverage"
            r"|generations? ?\d|gen ?\d|shitcam|dashcam|roof rack|driver|windscreen)"),
    ("infrastructure",
     r"\b(pole|bollard|sign|signage|signal|marking|guard ?rail|kerb|curb|bridge"
     r"|tunnel|bus stop|railway|tram|pylon|power line|wire|cable|street ?light"
     r"|lamp ?post|paving|asphalt|tarmac|junction|roundabout|road|highway|route"
     r"|motorway|shield|chevron|delineator|reflector|barrier|manhole|hydrant"
     r"|utility|pavement|sidewalk|crossing|parking|car park"
     # Electricity boxes and counters: a major family, especially in the
     # Philippines. Without keywords of their own they fell through to whatever
     # incidental word the description held — "the southern half of the island"
     # filed a metal box under landscape.
     #
     # `meter` only in a box context: bare, it would catch every summit given in
     # metres. `tube` is deliberately absent — one meta describes saguaro cacti
     # as "tall, straight tubes".
     r"|metal box|junction box|cable box|fuse box|electric(?:ity)? box|meter box"
     r"|meters? (?:board|setup|cover|cabinet)|counters?\b)"),
    ("architecture",
     r"\b(architect|building|house|housing|roof|facade|brick|balcon|window|wall"
     r"|church|mosque|temple|shrine|stupa|pagoda|synagogue|monaster|cathedral"
     r"|chapel|tower|castle|monument|museum|apartment|villa|hut|shack|garage"
     # `greenhouse` belongs to vegetation, not here: the spec files greenhouses
     # under Vegetation & Agriculture. Silos and barns do stay architecture.
     r"|silo|barn|granary|fence|chimney|door|gate|stadium|bunker)"),
    ("vegetation",
     r"\b(tree|forest|wood(?:land|ed)|vegetat|crop|field|farm|agricultur"
     r"|plantation|orchard|palm|grass|bush|shrub|pasture|paddy|vineyard|flower"
     # `cact` and not `cactus`: the plural is `cacti`.
     r"|cact|bamboo|moss|scrub|savanna|jungle|hedge|foliage|harvest"
     # A greenhouse is a building, but the spec files it under agriculture. It
     # must appear here and nowhere else, since architecture is checked first.
     r"|greenhouse)"),
    ("landscape",
     r"\b(mountain|peak|hill|ridge|valley|landscape|terrain|desert|dune|lake|river"
     r"|stream|coast|cliff|volcano|island|plateau|plain|snow|glacier|beach"
     r"|canyon|rocky|arid|barren|elevation|altitude|climate|fog|sand|soil"
     r"|erosion|horizon|scenery|lagoon|delta|fjord)"),
    # Last on purpose, and measured: only 45 metas in the corpus match culture
    # *and* an earlier rule, and in most of them the earlier rule is right — a
    # pole wearing the national colours is a pole, a mosque is a building. The
    # handful it gets wrong go to data/categories.json.
    #
    # `flags?\b` and not `flag`: `flagstone` is paving, not a flag.
    ("culture",
     r"\b(flags?\b|flagpole|religio|buddhis|muslim|islam|christian|hindu|shinto"
     r"|festival|patriot|national colou?r|domain|currency|traditional dress"
     r"|graffiti|mural|cemetery|grave)"),
]

_LANGUAGE_RE = re.compile(LANGUAGE)
_RULE_RES: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern)) for name, pattern in RULES
]


def infer_category(title: str, description: str) -> str:
    """The category a meta falls into, from its text alone.

    Never the last word: `data/categories.json` overrides this at build time for
    the cases the rules get wrong.
    """
    title, description = title.lower(), description.lower()
    if _LANGUAGE_RE.search(f"{title} {description}"):
        return "culture"
    for haystack in (title, description):
        for name, rule in _RULE_RES:
            if rule.search(haystack):
                return name
    return FALLBACK
