from cartometa.config import load_config


def test_load_config_reads_measured_constants():
    cfg = load_config()
    assert cfg.get("cream.rgb") == [255, 253, 235]
    assert cfg.get("red.hue_min") == 340.0
    assert cfg.get("silhouette.min_area_fraction") == 0.02


def test_get_returns_default_for_missing_key():
    cfg = load_config()
    assert cfg.get("nope.absent", 7) == 7
