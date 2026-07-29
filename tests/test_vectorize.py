import numpy as np
from shapely.geometry import Point
from cartometa.config import load_config
from cartometa.geo.calibrate import Calibration
from cartometa.geo.silhouette import Inset, find_inset
from cartometa.geo.vectorize import buffer_km, mask_to_geometry, zone_mask
from tests.fixtures import synthetic_meta_image

CALIB = Calibration(ax=0.01, bx=14.0, ay=-0.01, by=55.0, iou=0.99)

RED = (193, 40, 58, 255)


def _array(**kwargs):
    return np.array(synthetic_meta_image(**kwargs).convert("RGBA"))


def test_zone_mask_excludes_red_in_a_notch_outside_an_l_shaped_silhouette():
    """La silhouette de synthetic_meta_image est un rectangle : mask == bbox
    rectangle, donc un test qui ne mélange que ces fixtures ne peut pas
    distinguer un vrai masquage intra-silhouette d'un simple recadrage
    rectangulaire. Cette silhouette en L, construite directement, a un
    "notch" (coin manquant) qui est dans le rectangle englobant (bbox) mais
    hors de la silhouette elle-même : c'est là qu'on place le rouge
    parasite, mesuré comme réel sur `Poland-southern-hills` (75 px de rouge
    dans le rectangle de l'encart mais hors silhouette).
    """
    size = 100
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[..., 3] = 255  # fond opaque, non rouge

    mask = np.zeros((size, size), dtype=bool)
    mask[10:90, 10:90] = True
    mask[10:50, 10:50] = False  # coin manquant : silhouette en L
    inset = Inset(bbox=(10, 10, 90, 90), mask=mask, area_fraction=0.48)

    # Rouge parasite : dans le rectangle englobant (bbox), mais dans le
    # coin manquant, donc hors de la silhouette en L.
    rgba[20:30, 20:30, :3] = RED[:3]
    rgba[20:30, 20:30, 3] = 255

    # Rouge légitime : à l'intérieur de la silhouette en L.
    rgba[60:70, 60:70, :3] = RED[:3]
    rgba[60:70, 60:70, 3] = 255

    result = zone_mask(rgba, inset, load_config())

    assert result[60:70, 60:70].any(), "le rouge légitime dans la silhouette doit être retenu"
    assert not result[20:30, 20:30].any(), "le rouge du coin manquant (hors silhouette) doit être exclu"


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
