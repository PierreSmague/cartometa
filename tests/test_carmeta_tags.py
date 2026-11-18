import pytest

from cartometa.carmeta.tags import Canonical, classify, normalize_descriptor

ISO = frozenset({"DE", "FR", "NA", "ET", "BL"})
LEXICON = {key.lower(): key for key in (
    "Blue", "Black", "Gray", "No Car", "Smallcam", "Truck", "Antenna", "Snow",
    "BL", "Front Blur", "New Blur", "Exposed", "Exposed Back", "Blue Unexposed",
)}


def _classify(tag):
    return classify(tag, ISO, LEXICON)


@pytest.mark.parametrize("tag", [
    "───Month───", "═══Country═══", "2024", "1998", "7", "12", "24-06",
    "Clear", "Some Clouds", "Overcast", "Csa", "BSk", "Dfb", "ET", "P2",
    "Part 3", "No BL", "No Antenna", "No Front Blur", "No Snow", "DE", "FR",
    "Bayern", "Nordrhein-Westfalen", "Gen 4", "Normal Gen 4", "", "   ",
])
def test_dropped_families_give_nothing(tag):
    assert _classify(tag) is None


@pytest.mark.parametrize("tag, text, descriptor, year, antenna", [
    ("Blue 2024 (NA)", "Blue 2024 (NA)", "Blue", 2024, "NA"),
    ("Blue 24 (NA)", "Blue 2024 (NA)", "Blue", 2024, "NA"),
    ("Blue Car 2024", "Blue 2024", "Blue", 2024, None),
    ("Blue Car Antenna 2024", "Blue 2024 (A)", "Blue", 2024, "A"),
    ("Grey 2023", "Gray 2023", "Gray", 2023, None),
    ("  Blue   2023  (A) ", "Blue 2023 (A)", "Blue", 2023, "A"),
    ("Black 2025 (A + NA)", "Black 2025 (A+NA)", "Black", 2025, "A+NA"),
    ("No Car 2023", "No Car 2023", "No Car", 2023, None),
    ("Smallcam 25", "Smallcam 2025", "Smallcam", 2025, None),
    ("smallcam 2025", "Smallcam 2025", "Smallcam", 2025, None),
    ("Blue Unexposed 2024", "Blue Unexposed 2024", "Blue Unexposed", 2024, None),
    ("Ford 2022", "Ford 2022", "Ford", 2022, None),
])
def test_car_year_tags_reduce_to_a_triplet(tag, text, descriptor, year, antenna):
    assert _classify(tag) == Canonical("car_year", text, descriptor, year, antenna)


@pytest.mark.parametrize("tag, family, text", [
    ("BL", "bl", "BL"),
    ("Brakelight", "bl", "BL"),
    ("Antenna", "antenna", "Antenna"),
    ("Snow", "snow", "Snow"),
    ("Smallcam", "smallcam", "Smallcam"),
    ("Front Blur", "blur", "Front Blur"),
    ("New Blur", "blur", "New Blur"),
    ("Exposed", "exposed", "Exposed"),
    ("Exposed Back", "exposed", "Exposed Back"),
])
def test_standalone_clues_keep_one_spelling(tag, family, text):
    assert _classify(tag) == Canonical(family, text, text)


def test_bl_is_a_clue_before_being_a_country_code():
    # BL is Saint-Barthélemy's ISO code: the clue must win.
    assert _classify("BL").family == "bl"


@pytest.mark.parametrize("tag", ["©2026", "© 2026"])
def test_a_copyright_needs_no_lexicon(tag):
    assert _classify(tag) == Canonical("copyright", "©2026", None, year=2026)


def test_a_bare_descriptor_is_a_car_when_the_lexicon_knows_it():
    assert _classify("Black") == Canonical("car", "Black", "Black")
    assert _classify("Grey") == Canonical("car", "Gray", "Gray")
    # Known but still pending: a car all the same, arbitration decides later.
    assert _classify("Truck") == Canonical("car", "Truck", "Truck")


def test_anything_else_is_unknown():
    assert _classify("Zorglub") == Canonical("unknown", "Zorglub", "Zorglub")


@pytest.mark.parametrize("raw, expected", [
    ("Blue Car", "Blue"), ("Blue Car Antenna", "Blue"), ("Grey", "Gray"),
    ("No Car", "No Car"), ("No Car Antenna", "No Car"), ("Alberta Car", "Alberta"),
    ("Black / Grey", "Black / Gray"), ("Car", "Car"), ("  Blue   Striped ", "Blue Striped"),
])
def test_descriptors_lose_their_filler_words(raw, expected):
    assert normalize_descriptor(raw) == expected
