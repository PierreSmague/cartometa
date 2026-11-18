import base64

import numpy as np
import pytest

from cartometa.carmeta.zones import (
    KM_PER_DEG_LAT,
    KM_PER_DEG_LON,
    build_frame,
    cell_states_b64,
    coverage_b64,
    regional_gain,
    representative,
    tag_zones,
)


def _grid(n=200, step_km=1.0, lat0=10.0, lng0=10.0):
    """An n × n lattice of points `step_km` apart: (lat, lng, row, column)."""
    kx = KM_PER_DEG_LON * np.cos(np.radians(lat0 + n * step_km / KM_PER_DEG_LAT / 2))
    column, row = np.meshgrid(np.arange(n), np.arange(n))
    row, column = row.ravel(), column.ravel()
    return (lat0 + row * step_km / KM_PER_DEG_LAT, lng0 + column * step_km / kx,
            row, column)


def _chain(count, step_km=0.5, lat0=10.0, lng0=10.0):
    lat = np.full(count, lat0)
    lng = lng0 + np.arange(count) * step_km / (KM_PER_DEG_LON * np.cos(np.radians(lat0)))
    return lat, lng


@pytest.fixture(scope="module")
def country():
    lat, lng, row, column = _grid()
    return build_frame(lat, lng), row, column


def _gain(frame, mask):
    zones = tag_zones(frame, np.nonzero(mask)[0], 30)
    return regional_gain(frame, zones.points)


def test_the_frame_measures_the_coverage_and_its_spacing(country):
    frame, _, _ = country

    assert frame.size_km == pytest.approx(199, abs=2)
    assert frame.spacing_km == pytest.approx(1.0, abs=0.01)
    assert frame.link_km == pytest.approx(3.0, abs=0.03)
    assert frame.cell_km == pytest.approx(frame.size_km / 60)
    assert frame.total.sum() == 200 * 200
    assert not frame.wrapped


def test_the_analysis_cell_is_bounded():
    lat, lng, _, _ = _grid(n=30)           # ~30 km across: D/60 would be 0.5 km
    assert build_frame(lat, lng).cell_km == 1.5
    lat, lng, _, _ = _grid(n=60, step_km=40.0)   # ~2 400 km across
    assert build_frame(lat, lng).cell_km == 25.0


def test_a_chain_of_thirty_points_is_one_zone():
    lat, lng = _chain(30)
    frame = build_frame(lat, lng)

    zones = tag_zones(frame, np.arange(30), 30)

    assert zones.sizes == [30]
    assert zones.capture == 1.0
    assert sorted(zones.points.tolist()) == list(range(30))


def test_twenty_nine_points_are_no_zone():
    lat, lng = _chain(29)
    frame = build_frame(lat, lng)

    zones = tag_zones(frame, np.arange(29), 30)

    assert zones.count == 0 and zones.capture == 0.0 and len(zones.points) == 0


def test_isolated_points_are_ignored_and_lower_the_capture():
    lat, lng = _chain(30)
    # Ten lone points, each 50 km from everything.
    far_lat = 10.0 + (np.arange(10) + 1) * 50 / KM_PER_DEG_LAT
    frame = build_frame(np.concatenate([lat, far_lat]),
                        np.concatenate([lng, np.full(10, 10.0)]))

    zones = tag_zones(frame, np.arange(40), 30)

    assert zones.sizes == [30]
    assert zones.capture == pytest.approx(30 / 40)
    assert zones.points.max() < 30


def test_zones_are_numbered_largest_first():
    lat_a, lng_a = _chain(40)
    lat_b, lng_b = _chain(60, lat0=11.0)
    frame = build_frame(np.concatenate([lat_a, lat_b]), np.concatenate([lng_a, lng_b]))

    zones = tag_zones(frame, np.arange(100), 30)

    assert zones.sizes == [60, 40]
    assert set(zones.points[zones.labels == 0].tolist()) == set(range(40, 100))
    assert set(zones.cells[:, 2].tolist()) == {0, 1}


def test_the_representative_point_sits_in_the_middle_of_the_largest_zone():
    lat_a, lng_a = _chain(40)
    lat_b, lng_b = _chain(61, lat0=11.0)
    frame = build_frame(np.concatenate([lat_a, lat_b]), np.concatenate([lng_a, lng_b]))
    zones = tag_zones(frame, np.arange(101), 30)

    assert representative(frame, zones) == 40 + 30


def test_a_tag_present_everywhere_gains_nothing(country):
    frame, row, column = country
    assert _gain(frame, (row + column) % 3 == 0) == pytest.approx(0.0, abs=0.02)


def test_a_tag_confined_to_half_the_country_gains_about_half(country):
    frame, _, column = country
    assert _gain(frame, column < 100) == pytest.approx(0.50, abs=0.06)


def test_a_tag_covering_ninety_percent_gains_about_ten(country):
    frame, _, column = country
    assert _gain(frame, column < 180) == pytest.approx(0.10, abs=0.06)


def test_a_fine_checkerboard_gains_nothing(country):
    frame, row, column = country
    assert _gain(frame, ((row // 8) + (column // 8)) % 2 == 0) == pytest.approx(0.0, abs=0.02)


def test_no_zone_points_no_gain(country):
    frame, _, _ = country
    assert regional_gain(frame, np.array([], dtype=np.int64)) == 0.0


def test_a_cloud_across_the_antimeridian_stays_in_one_piece():
    lat = np.full(60, -17.0)
    lng = np.concatenate([np.linspace(179.80, 179.99, 30), np.linspace(-179.99, -179.80, 30)])
    frame = build_frame(lat, lng)

    assert frame.wrapped
    assert frame.x.max() - frame.x.min() < 50
    assert tag_zones(frame, np.arange(60), 30).sizes == [60]


def test_two_runs_cut_the_same_zones(country):
    _, row, column = country
    lat, lng, _, _ = _grid()
    first, second = build_frame(lat, lng), build_frame(lat, lng)
    members = np.nonzero(column < 100)[0]

    assert first.link_km == second.link_km
    assert np.array_equal(tag_zones(first, members, 30).cells,
                          tag_zones(second, members, 30).cells)


def test_the_report_bitmaps_cover_every_cell(country):
    frame, _, column = country
    zones = tag_zones(frame, np.nonzero(column < 100)[0], 30)

    coverage = np.unpackbits(np.frombuffer(base64.b64decode(coverage_b64(frame)), np.uint8))
    assert coverage[:frame.width * frame.height].sum() == (frame.total > 0).sum()

    packed = base64.b64decode(cell_states_b64(frame, zones.points))
    states = [(packed[i >> 2] >> ((i & 3) * 2)) & 3 for i in range(int(coverage.sum()))]
    # Zone on one side, eliminated on the far side, neither in between.
    assert set(states) == {0, 1, 2}
    assert states.count(1) == pytest.approx(len(states) / 2, rel=0.1)
