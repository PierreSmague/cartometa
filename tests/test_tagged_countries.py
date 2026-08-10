import json

import pytest

from cartometa.geo.reference import DATASET_NAME
from cartometa.tagged.countries import CountryIndex


def _pays(code, west, south, east, north):
    return {
        "type": "Feature",
        "properties": {"ISO_A2": code, "ISO_A2_EH": code},
        "geometry": {"type": "Polygon", "coordinates": [[
            [west, south], [east, south], [east, north], [west, north], [west, south],
        ]]},
    }


@pytest.fixture
def index(tmp_path):
    (tmp_path / DATASET_NAME).write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            _pays("AA", 0.0, 0.0, 10.0, 10.0),
            _pays("BB", 20.0, 0.0, 30.0, 10.0),
            # Code manquant, à la façon Natural Earth : jamais rattachable.
            _pays("-99", 40.0, 0.0, 50.0, 10.0),
        ],
    }), "utf-8")
    return CountryIndex(tmp_path)


def test_a_point_lands_in_its_country(index):
    assert index.country_of(5.0, 5.0) == "AA"
    assert index.country_of(5.0, 25.0) == "BB"


def test_a_point_just_offshore_snaps_to_the_nearest_country(index):
    # 0.05° à l'ouest de AA : dans le rayon de rattachement (~10 km).
    assert index.country_of(5.0, -0.05) == "AA"


def test_a_point_far_from_everything_is_dropped(index):
    assert index.country_of(5.0, 15.0) is None


def test_a_country_without_iso_code_never_matches(index):
    assert index.country_of(5.0, 45.0) is None
