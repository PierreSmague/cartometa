import json
from pathlib import Path

import pytest

from cartometa.geo.admin1 import ADMIN1_NAME, country_regions, region_geometry


def _box(x0, y0, x1, y1):
    return {"type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


FAKE = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"adm1_code": "POL-1", "iso_a2": "PL", "name": "Mazowieckie"},
     "geometry": _box(20.0, 51.0, 22.0, 53.0)},
    {"type": "Feature",
     "properties": {"adm1_code": "POL-2", "iso_a2": "pl", "name": None,
                    "name_en": "Malopolskie"},
     "geometry": _box(19.0, 49.0, 21.0, 50.5)},
    {"type": "Feature",
     "properties": {"adm1_code": "FRA-1", "iso_a2": "FR", "name": "Bretagne"},
     "geometry": _box(-5.0, 47.0, -1.0, 49.0)},
]}


@pytest.fixture
def cache_dir(tmp_path):
    (tmp_path / ADMIN1_NAME).write_text(json.dumps(FAKE), "utf-8")
    return tmp_path


def test_only_the_countrys_regions_are_extracted(cache_dir):
    regions = country_regions("PL", cache_dir)

    codes = {f["properties"]["code"] for f in regions["features"]}
    assert codes == {"POL-1", "POL-2"}


def test_the_country_code_is_compared_case_insensitively(cache_dir):
    """Natural Earth is not consistent about the case of iso_a2."""
    regions = country_regions("pl", cache_dir)

    assert len(regions["features"]) == 2


def test_the_name_falls_back_to_name_en_when_name_is_empty(cache_dir):
    regions = country_regions("PL", cache_dir)

    noms = {f["properties"]["code"]: f["properties"]["name"] for f in regions["features"]}
    assert noms["POL-2"] == "Malopolskie"


def test_the_extraction_is_cached_per_country(cache_dir):
    country_regions("PL", cache_dir)

    assert (cache_dir / "admin1" / "PL.geojson").exists()


def test_the_big_file_is_no_longer_read_after_extraction(cache_dir):
    country_regions("PL", cache_dir)
    (cache_dir / ADMIN1_NAME).unlink()

    # The per-country cache must be enough: that is the whole point of extracting.
    assert len(country_regions("PL", cache_dir)["features"]) == 2


def test_country_without_region_raises_keyerror_without_writing_a_cache(cache_dir):
    with pytest.raises(KeyError):
        country_regions("ZZ", cache_dir)

    # An empty cache would prevent any further attempt forever.
    assert not (cache_dir / "admin1" / "ZZ.geojson").exists()


def test_the_download_is_injectable(tmp_path):
    appels = []

    def downloader(url: str, dest: Path) -> None:
        appels.append(url)
        dest.write_text(json.dumps(FAKE), "utf-8")

    country_regions("PL", tmp_path, downloader=downloader)

    assert len(appels) == 1


def test_region_geometry_by_code(cache_dir):
    geom = region_geometry("PL", "POL-1", cache_dir)

    assert geom.bounds == (20.0, 51.0, 22.0, 53.0)


def test_region_geometry_unknown_code(cache_dir):
    with pytest.raises(KeyError):
        region_geometry("PL", "POL-99", cache_dir)


def test_region_geometry_is_memoized(cache_dir):
    assert (
        region_geometry("PL", "POL-1", cache_dir)
        is region_geometry("PL", "POL-1", cache_dir)
    )
