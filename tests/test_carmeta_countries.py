import json

import numpy as np
import pytest

from cartometa.carmeta.countries import CountryAssigner
from cartometa.geo.reference import DATASET_NAME
from cartometa.tagged.countries import CountryIndex


def _country(code, west, south, east, north):
    return {
        "type": "Feature",
        "properties": {"ISO_A2": code, "ISO_A2_EH": code},
        "geometry": {"type": "Polygon", "coordinates": [[
            [west, south], [east, south], [east, north], [west, north], [west, south],
        ]]},
    }


@pytest.fixture
def cache(tmp_path):
    (tmp_path / DATASET_NAME).write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            _country("AA", 0.0, 0.0, 10.0, 10.0),
            _country("BB", 20.0, 0.0, 30.0, 10.0),
            # Missing code, the Natural Earth way: never attachable.
            _country("-99", 40.0, 0.0, 50.0, 10.0),
        ],
    }), "utf-8")
    return tmp_path


def _codes(assigner, points):
    lat = np.array([p[0] for p in points])
    lng = np.array([p[1] for p in points])
    return [assigner.codes[i] if i >= 0 else None for i in assigner.assign(lat, lng)]


def test_points_land_in_their_country(cache):
    assigner = CountryAssigner(cache)

    assert _codes(assigner, [(5.0, 5.0), (5.0, 25.0)]) == ["AA", "BB"]
    assert assigner.iso == {"AA", "BB"}


def test_a_point_just_offshore_snaps_to_the_nearest_country(cache):
    # 0.05° west of AA: within the snapping radius (~10 km).
    assert _codes(CountryAssigner(cache), [(5.0, -0.05)]) == ["AA"]


def test_a_point_far_from_everything_is_dropped(cache):
    assert _codes(CountryAssigner(cache), [(5.0, 15.0)]) == [None]


def test_a_country_without_iso_code_never_matches(cache):
    assert _codes(CountryAssigner(cache), [(5.0, 45.0)]) == [None]


def test_no_points_no_work(cache):
    assert len(CountryAssigner(cache).assign(np.array([]), np.array([]))) == 0


def test_it_agrees_with_the_point_by_point_index(cache):
    rng = np.random.default_rng(1)
    lat = rng.uniform(-2, 12, 500)
    lng = rng.uniform(-2, 52, 500)
    index = CountryIndex(cache)
    assigner = CountryAssigner(cache)

    expected = [index.country_of(a, b) for a, b in zip(lat, lng)]

    assert _codes(assigner, list(zip(lat, lng))) == expected
