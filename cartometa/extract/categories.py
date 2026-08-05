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
    r"|script|alphabet|diacritic|umlaut|tilde|cedilla"
    r"|language|bilingual|transliterat|spelling"
    # A quoted word is the single most common language clue in the corpus: "the
    # Catalan word for street is carrer", "uses the word ALTO on stop signs".
    # 55 metas turn on one, and they were scattered across three categories
    # before this. `in other words` is excluded as the filler it is.
    r"|(?<!in other )\bwords?\b)"
)
# `lettering` was removed after measurement: all 11 metas containing it are pole
# plates, stickers, street-name signs and number plates. It describes the styling
# of text, not a writing system, and it was dragging every one of them into
# Culture.

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
    # `driver` was removed: "an arrow informs drivers where the shoulder line
    # is" is road paint, not a car meta.
    #
    # Number plates live here: the plate is on the vehicle. Without them,
    # `lettering` sent one plate meta to Culture while an identical one landed in
    # Car — the same clue in two categories is worse than either choice.
    ("car", r"\b(google car|street ?view car|follow car"
            r"|(?:the|a|white|blue|grey|gray|black|red|yellow|green|silver|dark"
            r"|light)\s"
            r"cars?\b|vehicle|camera|antenna|blur|rift|snorkel|trekker|coverage"
            r"|generations? ?\d|gen ?\d|shitcam|dashcam|roof rack|windscreen"
            r"|(?:number|licence|license|front|rear) plates?\b|plates? with"
            # The vehicle's own kit and the vehicles Google drove: the Mongolian
            # tent on the roof, the trucks used in place of a car.
            r"|\btents?\b|\btrucks?\b|tripod)"),
    ("infrastructure",
     r"\b(pole|bollard|sign|signage|signal|marking|guard ?rail|kerb|curb|bridge"
     r"|tunnel|bus stop|railway|tram|pylon|power line|wire|cable|street ?light"
     r"|lamp ?post|paving|asphalt|tarmac|junction|roundabout|road|highway|route"
     r"|motorway|shield|chevron|delineator|reflector|barrier|manhole|hydrant"
     r"|utility|pavement|sidewalk|crossing|parking|car park|arrow|shoulder"
     # Roadside markers and posts, street lighting, street furniture: whole
     # families that had no keyword and fell through to `autre`.
     #
     # `\bposts?\b` and not `post`: `postal` is not a post. `\bbus(?:es)?\b`
     # anchored both sides: `bush` is not a bus.
     r"|waystone|marker|\bposts?\b|lamp|\bbins?\b|insulator|speed bump|turbine"
     # Driving side is a property of the road, by the owner's decision.
     r"|drives on the"
     # Public transport is infrastructure; other local vehicles are culture.
     r"|\bbus(?:es)?\b|\btrams?\b|\btaxis?\b"
     # Road paint. `line` only with a qualifier: bare, it would file tree lines
     # and snow lines here, since infrastructure is checked before vegetation.
     r"|(?:centre|center|middle|outer|edge|side|give-?way|dashed|solid|double"
     r"|white|yellow|blue|red) lines?\b"
     r"|traffic cone|\bcones?\b|water tank|\bcanals?\b|telephone booth|\bbooths?\b"
     r"|power plant"
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
     r"|silo|barn|granary|fence|chimney|door|gate|stadium|bunker|ruin"
     r"|skyscraper|skyline|fortress|\bforts?\b)"),
    ("vegetation",
     r"\b(tree|forest|wood(?:land|ed)|vegetat|crop|field|farm|agricultur"
     # `rice` as well as `paddy`: the paddy is the field, the rice is the crop,
     # and "Fully-grown rice" names only the crop.
     r"|plantation|orchard|palm|grass|bush|shrub|pasture|paddy|rice|vineyard|flower"
     # `cact` and not `cactus`: the plural is `cacti`.
     r"|cact|bamboo|moss|scrub|savanna|jungle|hedge|foliage|harvest"
     # Named species: the generic words were present, the species were not, so
     # "Aleppo pines" and "Eucalyptus" fell through to `autre`.
     r"|pine|eucalyptus|sunflower|\bcorn\b|maize|wheat|\btea\b|coffee|banana"
     r"|coconut|olive|birch|spruce|\boaks?\b|poplar|willow|acacia|baobab"
     r"|cotton|sugarcane|succulent|fern|reed|lavender|teak|haystack|\bhay\b"
     r"|lupine|\bwine\b|vine\b"
     # A greenhouse is a building, but the spec files it under agriculture. It
     # must appear here and nowhere else, since architecture is checked first.
     r"|greenhouse)"),
    ("landscape",
     # `mount\b` as well as `mountain`: metas say "Mount Tavor".
     r"\b(mountain|mount\b|peak|hill|ridge|valley|landscape|terrain|desert|dune"
     r"|lake|river"
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
     # Named denominations as well as `religio`: metas say "Catholic country",
     # never "religious country".
     r"\b(flags?\b|flagpole|religio|buddhis|muslim|islam|christian|catholic"
     r"|orthodox|protestant|lutheran|hindu|shinto"
     r"|festival|patriot|national colou?r|domain|currency|traditional dress"
     r"|graffiti|mural|cemetery|grave|obituar"
     # Immaterial conventions, alongside the `domain` and `currency` the spec
     # already files here: dialling plans, toponymy, advertising and brands.
     # Local vehicles other than public transport land here too, by the owner's
     # decision.
     r"|area code|landline|dialling code|phone number|town names|place names"
     r"|city (?:and state )?names|state names"
     r"|advertis|billboard|\bbrands?\b|restaurant chain"
     # Local vehicles that are not public transport, per the owner's decision.
     r"|tuk-?tuk|tricycle|rickshaw|\bcarts?\b|traditional clothing)"),
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
