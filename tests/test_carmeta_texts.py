from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from cartometa.carmeta.rules import Rules, load_rules
from cartometa.carmeta.tags import classify
from cartometa.carmeta.texts import description, maps_url, meta_id, title

RULES = load_rules(Path(__file__).resolve().parents[1] / "data" / "carmeta" / "rules.json")


def _row(tag):
    canonical = classify(tag, frozenset(), RULES.lexicon_index)
    return {"canonical": canonical.text, "family": canonical.family,
            "lexicon_key": canonical.lexicon_key, "year": canonical.year,
            "antenna": canonical.antenna}


@pytest.mark.parametrize("tag, expected", [
    ("Blue 2024 (NA)", "Blue car, no antenna · 2024"),
    ("Blue 2023 (A)", "Blue car, antenna · 2023"),
    ("Black 2025 (A+NA)", "Black car · 2025"),
    ("Black 2025", "Black car · 2025"),
    ("No Car 2023", "No car visible · 2023"),
    ("Smallcam 2025", "Smallcam · 2025"),
    ("©2025", "©2025 copyright"),
    ("BL", "Brake light"),
    ("Brakelight", "Brake light"),
    ("Antenna", "Antenna"),
    ("Smallcam", "Smallcam"),
    ("Blue Unexposed 2024", "Blue car, unexposed · 2024"),
])
def test_titles_follow_the_specification_table(tag, expected):
    assert title(_row(tag), RULES) == expected


def test_the_description_says_what_is_seen_the_year_and_the_point_count():
    assert description(_row("Blue Unexposed 2024"), RULES, 13750) == (
        "Street View coverage from 2024 shot with the unexposed blue car. "
        "Footprint computed from 13,750 locations tagged by carmeta.")


@pytest.mark.parametrize("tag, start", [
    ("Blue 2024 (NA)", "Street View coverage from 2024 shot with the blue car, no antenna visible."),
    ("Blue 2023 (A)", "Street View coverage from 2023 shot with the blue car, antenna visible."),
    ("No Car 2023", "Street View coverage from 2023 where the Google car is not visible."),
    ("©2025", "Street View coverage carrying the ©2025 Google copyright."),
    ("Snow", "Street View coverage shot in the snow."),
    ("BL", "Street View coverage where the car's brake light is visible."),
])
def test_one_sentence_per_family(tag, start):
    text = description(_row(tag), RULES, 31)

    assert text == f"{start} Footprint computed from 31 locations tagged by carmeta."


def test_a_wording_missing_from_the_lexicon_falls_back_on_the_key():
    row = {"canonical": "Ford 2022", "family": "car_year", "lexicon_key": "Ford",
           "year": 2022, "antenna": None}

    assert title(row, Rules()) == "Ford · 2022"
    assert description(row, Rules(), 40).startswith(
        "Street View coverage from 2022 shot with the ford.")


def test_the_id_depends_on_country_and_canonical_form_only():
    assert meta_id("MX", "Blue 2024") == meta_id("MX", "Blue 2024")
    assert meta_id("MX", "Blue 2024") != meta_id("US", "Blue 2024")
    assert meta_id("MX", "Blue 2024") != meta_id("MX", "Blue 2023")
    identifier = meta_id("MX", "Blue Unexposed 2024")
    assert identifier.startswith("car-") and len(identifier) == 10
    assert all(c in "0123456789abcdef" for c in identifier[4:])


def test_the_street_view_link_points_at_the_panorama():
    url = maps_url({"lat": 19.4, "lng": -99.1, "pano": "abc DEF&x", "heading": 271.54}, -35)

    assert url.startswith("https://www.google.com/maps/@?api=1&map_action=pano&pano=abc+DEF%26x")
    query = parse_qs(urlparse(url).query)
    assert query == {"api": ["1"], "map_action": ["pano"], "pano": ["abc DEF&x"],
                     "viewpoint": ["19.4,-99.1"], "heading": ["271.5"], "pitch": ["-35"]}
