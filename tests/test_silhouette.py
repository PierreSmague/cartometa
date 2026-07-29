import numpy as np
from cartometa.config import load_config
from cartometa.geo.silhouette import find_inset
from tests.fixtures import synthetic_meta_image


def _array(**kwargs):
    return np.array(synthetic_meta_image(**kwargs).convert("RGBA"))


def test_finds_inset_at_measured_relative_position():
    inset = find_inset(_array(), load_config())
    assert inset is not None
    x0, y0, x1, y1 = inset.bbox
    assert 0.70 < x0 / 1920 < 0.73
    assert 0.45 < y0 / 943 < 0.48


def test_returns_none_when_no_inset_present():
    assert find_inset(_array(with_inset=False), load_config()) is None


def test_mask_includes_red_zone_so_shape_is_not_hollowed():
    """La zone rouge remplace le crème : sans l'union, la silhouette serait trouée."""
    inset = find_inset(_array(red_shape="zone"), load_config())
    plain = find_inset(_array(red_shape=None), load_config())
    assert abs(inset.area_fraction - plain.area_fraction) < 0.005


def test_parasite_red_in_photo_is_outside_the_mask():
    inset = find_inset(_array(parasite_red=True), load_config())
    x0, _, _, _ = inset.bbox
    assert x0 > 1000  # la rose des vents est à gauche, hors silhouette
    assert not inset.mask[:, :1000].any()


def test_scale_invariance_between_1920_and_800():
    big = find_inset(_array(size=(1920, 943)), load_config())
    small = find_inset(_array(size=(800, 393)), load_config())
    assert abs(big.bbox[0] / 1920 - small.bbox[0] / 800) < 0.02
