import numpy as np
from PIL import Image, ImageDraw

from cartometa.config import load_config
from cartometa.geo.silhouette import find_inset, inset_variants, touches_image_edge
from tests.fixtures import synthetic_meta_image

CREAM = (255, 253, 235, 255)


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


def _archipelago_array(size=(600, 400)):
    """Deux « îles » crème disjointes sur fond blanc opaque."""
    img = Image.new("RGBA", size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, 250, 200], fill=CREAM)    # grande île
    draw.rectangle([400, 250, 550, 370], fill=CREAM)  # petite île
    return np.array(img)


def test_variants_single_component_returns_only_largest():
    variants = inset_variants(_array(parasite_red=False), load_config())
    assert len(variants) == 1
    assert variants[0].variant == "largest"


def test_variants_parasite_red_creates_multi_candidate_left_to_iou_arbitration():
    """Un rouge parasite dans la photo produit une variante multi polluée :
    c'est assumé, l'IoU de calibration l'écartera au tournoi."""
    variants = inset_variants(_array(parasite_red=True), load_config())
    assert [v.variant for v in variants] == ["largest", "multi"]


def test_variants_archipelago_offers_multi_union():
    variants = inset_variants(_archipelago_array(), load_config())
    assert [v.variant for v in variants] == ["largest", "multi"]
    largest, multi = variants
    # La variante multi couvre les deux îles, la simple une seule.
    assert not largest.mask[250:370, 400:550].any()
    assert multi.mask[100:150, 100:200].all() and multi.mask[280:350, 430:520].all()
    assert multi.bbox == (50, 50, 551, 371)
    assert multi.area_fraction > largest.area_fraction


def test_find_inset_still_returns_largest_component():
    inset = find_inset(_archipelago_array(), load_config())
    assert inset.variant == "largest"
    assert not inset.mask[250:370, 400:550].any()


def test_touches_image_edge():
    interior = np.zeros((50, 50), dtype=bool)
    interior[10:40, 10:40] = True
    assert not touches_image_edge(interior)
    cropped = np.zeros((50, 50), dtype=bool)
    cropped[10:40, 30:50] = True  # collé au bord droit
    assert touches_image_edge(cropped)
