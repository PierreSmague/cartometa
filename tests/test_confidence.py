from shapely.geometry import Point, box
from cartometa.config import load_config
from cartometa.geo.confidence import evaluate

CFG = load_config()
GOOD = box(18.0, 51.0, 20.0, 52.0)


def _evaluate(**overrides):
    kwargs = dict(
        geometry=GOOD, tier="regional", calib_iou=0.97, latlon=(51.5, 19.0),
        component_count=1, touches_border=False, area_fraction_of_country=0.15, cfg=CFG,
    )
    kwargs.update(overrides)
    return evaluate(**kwargs)


def test_clean_case_scores_high_without_warnings():
    score, warnings = _evaluate()
    assert score > 0.8 and warnings == []


def test_maps_point_outside_polygon_is_a_warning_and_lowers_score():
    score, warnings = _evaluate(latlon=(45.0, 5.0))
    assert any("hors du polygone" in w for w in warnings)
    assert score < 0.5


def test_missing_geometry_scores_zero():
    score, warnings = _evaluate(geometry=None)
    assert score == 0.0
    assert any("aucune géométrie" in w for w in warnings)


def test_low_calibration_iou_is_flagged():
    _, warnings = _evaluate(calib_iou=0.60)
    assert any("calibration" in w for w in warnings)


def test_many_components_suggest_parasite_red():
    _, warnings = _evaluate(component_count=9)
    assert any("composantes" in w for w in warnings)


def test_border_touching_zone_is_flagged_as_possibly_truncated():
    _, warnings = _evaluate(touches_border=True)
    assert any("tronquée" in w for w in warnings)


def test_near_national_coverage_suggests_using_country_polygon():
    _, warnings = _evaluate(area_fraction_of_country=0.97)
    assert any("quasi-totalité" in w for w in warnings)
