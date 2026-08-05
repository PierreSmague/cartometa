import json
from pathlib import Path

import pytest
from shapely.geometry import shape
from cartometa.geo.reference import (
    DATASET_NAME,
    country_code_for_name,
    country_geometry,
    ensure_dataset,
)

FAKE = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"ISO_A2": "PL", "ISO_A2_EH": "PL", "NAME": "Poland"},
     "geometry": {"type": "Polygon", "coordinates": [[[14.0, 49.0], [24.0, 49.0], [24.0, 55.0], [14.0, 55.0], [14.0, 49.0]]]}}]}

# Self-intersecting bow tie: a geometry invalid in the shapely/OGC sense.
INVALID = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"ISO_A2": "IV", "ISO_A2_EH": "IV", "NAME": "Invalidia"},
     "geometry": {"type": "Polygon", "coordinates": [[[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0], [0.0, 0.0]]]}}]}


@pytest.fixture
def cache_dir(tmp_path):
    (tmp_path / "ne_10m_admin_0_countries.geojson").write_text(json.dumps(FAKE), "utf-8")
    return tmp_path


@pytest.fixture
def invalid_cache_dir(tmp_path):
    (tmp_path / "ne_10m_admin_0_countries.geojson").write_text(json.dumps(INVALID), "utf-8")
    return tmp_path


def test_country_geometry_returns_shapely_geometry(cache_dir):
    geom = country_geometry("PL", cache_dir)
    assert geom.is_valid
    assert geom.bounds == (14.0, 49.0, 24.0, 55.0)


def test_unknown_country_raises(cache_dir):
    with pytest.raises(KeyError):
        country_geometry("ZZ", cache_dir)


def test_country_geometry_is_memoized(cache_dir):
    """Two calls for the same country must not rebuild the shapely geometry:
    resolve_pieces will ask for the national silhouette once per country-tier
    meta (37 times for the US)."""
    assert country_geometry("PL", cache_dir) is country_geometry("PL", cache_dir)


def test_invalid_source_geometry_is_repaired(invalid_cache_dir):
    # The source polygon is a self-intersecting bow tie: invalid in the OGC sense.
    raw = shape(INVALID["features"][0]["geometry"])
    assert not raw.is_valid, "test precondition: the source geometry must be invalid"

    geom = country_geometry("IV", invalid_cache_dir)
    assert geom.is_valid


def test_failed_download_leaves_no_file_at_final_path(tmp_path):
    def failing_downloader(url: str, dest: Path) -> None:
        # Simulates a network outage during the download: the temp file is partially
        # written, then the operation fails.
        dest.write_text("truncated content, not valid JSON", "utf-8")
        raise ConnectionError("simulated network outage")

    with pytest.raises(ConnectionError):
        ensure_dataset(tmp_path, downloader=failing_downloader)

    assert not (tmp_path / DATASET_NAME).exists()
    # No temporary file must be left lying around either.
    leftovers = list(tmp_path.glob("*"))
    assert leftovers == []


NAMED = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"ISO_A2": "BW", "ISO_A2_EH": "BW", "NAME": "Botswana",
                    "ADMIN": "Botswana", "FORMAL_EN": "Republic of Botswana"},
     "geometry": {"type": "Polygon", "coordinates": [[[20.0, -26.0], [29.0, -26.0], [29.0, -17.0], [20.0, -17.0], [20.0, -26.0]]]}},
    {"type": "Feature",
     "properties": {"ISO_A2": "-99", "ISO_A2_EH": "-99", "NAME": "Sans Code"},
     "geometry": {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]}}]}


@pytest.fixture
def named_cache_dir(tmp_path):
    (tmp_path / DATASET_NAME).write_text(json.dumps(NAMED), "utf-8")
    return tmp_path


def test_code_from_a_lowercase_slug(named_cache_dir):
    assert country_code_for_name("botswana", named_cache_dir) == "BW"


def test_code_from_a_dashed_slug(named_cache_dir):
    """Multi-word Plonk It slugs use dashes."""
    assert country_code_for_name("republic-of-botswana", named_cache_dir) == "BW"


def test_an_unknown_name_returns_none(named_cache_dir):
    assert country_code_for_name("atlantide", named_cache_dir) is None


def test_a_code_absent_from_natural_earth_returns_none(named_cache_dir):
    """Natural Earth encodes a missing ISO code as "-99", not as an empty value."""
    assert country_code_for_name("sans-code", named_cache_dir) is None


