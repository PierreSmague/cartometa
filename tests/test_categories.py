import pytest

from cartometa.extract.categories import CATEGORIES, FALLBACK, infer_category


def test_the_seven_categories_are_declared_in_display_order():
    assert CATEGORIES == (
        "infrastructure", "vegetation", "landscape",
        "architecture", "car", "culture", "autre",
    )
    assert FALLBACK == "autre"


@pytest.mark.parametrize("text,expected", [
    ("Bollards are white with a red stripe", "infrastructure"),
    ("Utility poles have a yellow band", "infrastructure"),
    ("Direction signs are yellow", "infrastructure"),
    ("Guardrails are made of unpainted wood", "infrastructure"),
    ("Orchards are concentrated around Grojec", "vegetation"),
    ("Dense pine forest covers the north", "vegetation"),
    ("Greenhouses line the southern coast", "vegetation"),
    ("The tallest mountains are in the north", "landscape"),
    ("Bizerte Lake has teal coloured water", "landscape"),
    ("A lone tall ridge with a striated texture", "landscape"),
    ("Some houses have thatched roofs", "architecture"),
    ("These distinctive silos are found inland", "architecture"),
    ("The cathedral features prominently", "architecture"),
    ("The Google car is a white Subaru", "car"),
    ("A blurry rift is visible on the left", "car"),
    ("Generation 2 coverage is common here", "car"),
    ("Buddhist prayer flags are a common sight", "culture"),
    ("Things are painted in the national flag colours", "culture"),
    ("Something entirely unrelated", "autre"),
])
def test_infer_category(text, expected):
    assert infer_category(text, "") == expected


def test_every_category_is_reachable_from_some_input():
    """A category no input can produce is dead weight in the filter bar."""
    produced = {infer_category(t, "") for t in (
        "bollard", "forest", "mountain", "roof",
        "google car", "national flag", "nothing at all",
    )}
    assert produced == set(CATEGORIES)


def test_language_beats_the_object_being_looked_at():
    """The one exception to object-wins: a Cyrillic sign is Culture."""
    assert infer_category("Road signs are written in Cyrillic", "") == "culture"


def test_language_in_the_description_beats_an_object_in_the_title():
    """infer_category resolves the title before the description, so the
    exception has to be evaluated over both at once or it never fires here."""
    assert infer_category("Direction signs", "are written in Cyrillic") == "culture"


def test_title_takes_precedence_over_description():
    assert infer_category("Bollards", "seen near many trees") == "infrastructure"


def test_substring_of_unrelated_word_does_not_match():
    # "tree" is a substring of "street": must not trigger vegetation.
    assert infer_category("Street architecture", "Nothing about plants") == "architecture"


def test_latin_america_is_not_a_writing_system():
    """`latin` alone would drag every South American meta into Culture."""
    assert infer_category("The tallest mountains in Latin America", "") == "landscape"


def test_a_car_park_is_not_a_car_meta():
    """Bare `car` in the car rule would swallow parking infrastructure."""
    assert infer_category("Multi-storey car parks are common", "") != "car"


def test_flagstone_is_not_a_flag():
    """`flag` unanchored would file paving under Culture."""
    assert infer_category("Pavements are made of grey flagstone", "") == "infrastructure"


def test_a_greenhouse_is_vegetation_not_architecture():
    """It is a building, but the spec files greenhouses under agriculture and
    architecture is evaluated first — so the word must not appear in both rules."""
    assert infer_category("Greenhouses cover the hillsides", "") == "vegetation"


def test_a_utility_meter_box_is_infrastructure():
    """Electricity boxes are a major meta family, especially in the Philippines.

    Without a keyword of their own they fell through to whatever incidental word
    the description happened to contain — "the southern half of the island" made
    a metal box a landscape meta.
    """
    assert infer_category(
        "Cebu metal box",
        "These metal box are more common in the southern half of the island",
    ) == "infrastructure"
    assert infer_category("Aklan meters board", "") == "infrastructure"
    assert infer_category("Guimaras counters", "yellow covers") == "infrastructure"


def test_a_measurement_in_metres_does_not_make_a_meta_infrastructure():
    """`meter` is only accepted in a box context: bare, it would file every
    mountain given in metres under Infrastructures."""
    assert infer_category("Peaks rise over 3000 meters", "") == "landscape"


def test_a_cactus_shaped_like_a_tube_stays_vegetation():
    """`tube` was rejected from the infrastructure rule for exactly this meta.
    If someone adds it, this test says why they should not."""
    assert infer_category(
        "Saguaro cacti are most commonly shaped like tall, straight tubes", ""
    ) == "vegetation"


def test_named_denominations_are_culture():
    """`christian` alone missed the word every meta actually uses."""
    assert infer_category("Poland is one of the most Catholic countries", "") == "culture"
    assert infer_category("Orthodox crosses have three bars", "") == "culture"


def test_rice_is_vegetation():
    """`paddy` covers the field, not the crop: "Fully-grown rice" fell through."""
    assert infer_category("Fully-grown rice", "") == "vegetation"


def test_licence_plates_are_car_metas():
    """The plate is on the vehicle. Before this, `lettering` sent a plate meta to
    Culture, while an identical Sri Lankan one landed in Car — the same clue in
    two categories is worse than either choice."""
    assert infer_category(
        "Liechtenstein uses black plates with white lettering", ""
    ) == "car"
    assert infer_category(
        "Vehicles have long white front plates and short yellow rear plates", ""
    ) == "car"


def test_the_word_driver_does_not_make_a_road_marker_a_car_meta():
    """"An arrow informs drivers where the shoulder line is" is road paint."""
    assert infer_category(
        "This infrastructural arrow informs drivers of where the shoulder line is", ""
    ) == "infrastructure"


def test_a_word_quoted_from_a_sign_is_a_language_clue():
    """55 metas in the corpus turn on a written word, and they were split across
    `autre`, `infrastructure` and `culture` — the same clue in three categories.
    The agreed rule settles it: language wins even when carried by a sign."""
    assert infer_category("The Catalan word for street is carrer", "") == "culture"
    assert infer_category("Mexico uses the word ALTO on stop signs", "") == "culture"
    assert infer_category(
        "These one-way traffic signs, with the word Einbahn written on them", ""
    ) == "culture"


def test_in_other_words_is_not_a_language_clue():
    """The filler phrase must not drag a meta into Culture."""
    assert infer_category(
        "Bollards are short, in other words easy to miss", ""
    ) == "infrastructure"


def test_a_follow_car_is_a_car_meta():
    """The colour list gates bare `car`, so it has to be wide enough: a yellow
    follow car was landing in Architecture on the word `windows`."""
    assert infer_category(
        "A yellow follow car with two front windows trails the Google truck", ""
    ) == "car"


def test_an_incidental_infrastructure_word_outranks_culture():
    """A known and accepted limitation, measured before being accepted.

    The rules cannot tell an incidental mention ("flags hang over the road")
    from a subject ("roads are lined with flags"), and infrastructure is
    evaluated before culture. Only 45 metas in the corpus hit this collision and
    the earlier rule is right in most of them, so the order stays and the
    exceptions go to `data/categories.json`.

    This test exists to record the behaviour, not to bless it. If it starts
    failing because the order changed, re-measure the corpus first.
    """
    assert infer_category("Prayer flags hang over the road", "") == "infrastructure"
