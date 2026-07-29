import numpy as np
from shapely.geometry import Point
from cartometa.config import load_config
from cartometa.geo.calibrate import Calibration
from cartometa.geo.silhouette import find_inset
from cartometa.geo.vectorize import buffer_km, mask_to_geometry, zone_mask
from tests.fixtures import synthetic_meta_image

CALIB = Calibration(ax=0.01, bx=14.0, ay=-0.01, by=55.0, iou=0.99)


def _array(**kwargs):
    return np.array(synthetic_meta_image(**kwargs).convert("RGBA"))


def test_zone_mask_excludes_parasite_red_from_the_photo():
    rgba = _array(red_shape="zone", parasite_red=True)
    inset = find_inset(rgba, load_config())
    mask = zone_mask(rgba, inset, load_config())
    assert mask.any()
    assert not mask[:, :1000].any()  # la rose des vents est écartée


def test_zone_mask_is_empty_when_no_red_zone():
    rgba = _array(red_shape=None, parasite_red=False)
    inset = find_inset(rgba, load_config())
    assert not zone_mask(rgba, inset, load_config()).any()


def test_mask_to_geometry_produces_a_valid_polygon():
    rgba = _array(red_shape="zone")
    inset = find_inset(rgba, load_config())
    geom = mask_to_geometry(zone_mask(rgba, inset, load_config()), CALIB, load_config())
    assert geom is not None
    assert geom.is_valid
    assert geom.geom_type in ("Polygon", "MultiPolygon")


def test_every_ring_is_closed_and_non_self_intersecting():
    rgba = _array(red_shape="zone")
    inset = find_inset(rgba, load_config())
    geom = mask_to_geometry(zone_mask(rgba, inset, load_config()), CALIB, load_config())
    parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    assert parts
    for part in parts:
        assert part.is_valid
        for ring in [part.exterior, *part.interiors]:
            assert ring.is_ring, "anneau non fermé"
            assert ring.is_simple, "anneau auto-intersectant"


def test_mask_to_geometry_returns_none_on_empty_mask():
    assert mask_to_geometry(np.zeros((50, 50), dtype=bool), CALIB, load_config()) is None


def test_buffer_km_grows_the_shape_outward():
    point = Point(19.0, 52.0).buffer(0.1)
    grown = buffer_km(point, 10.0)
    assert grown.area > point.area
    assert grown.contains(point)
