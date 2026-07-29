import warnings

import numpy as np
import pytest
from shapely.geometry import box
from cartometa.config import load_config
from cartometa.geo.calibrate import Calibration, fit_calibration, load_calibration, save_calibration


def _rect_mask(shape=(400, 400), x0=100, x1=300, y0=50, y1=250):
    mask = np.zeros(shape, dtype=bool)
    mask[y0:y1, x0:x1] = True
    return mask


def _cross_mask(shape=(400, 400)):
    """Une silhouette en croix : ne peut pas bien se superposer à un
    rectangle, quels que soient les paramètres affines choisis."""
    mask = np.zeros(shape, dtype=bool)
    mask[150:250, 50:350] = True
    mask[50:350, 150:250] = True
    return mask


def test_fit_recovers_transform_for_a_rectangle():
    country = box(14.0, 49.0, 24.0, 55.0)
    calib = fit_calibration(_rect_mask(), country, load_config())
    lon, lat = calib.pixel_to_lonlat(100, 50)
    assert abs(lon - 14.0) < 0.2 and abs(lat - 55.0) < 0.2
    lon, lat = calib.pixel_to_lonlat(300, 250)
    assert abs(lon - 24.0) < 0.2 and abs(lat - 49.0) < 0.2


def test_latitude_axis_is_inverted():
    calib = fit_calibration(_rect_mask(), box(14.0, 49.0, 24.0, 55.0), load_config())
    assert calib.ay < 0


def test_iou_is_high_for_matching_shapes():
    calib = fit_calibration(_rect_mask(), box(14.0, 49.0, 24.0, 55.0), load_config())
    assert calib.iou > 0.95


def test_roundtrip_through_disk(tmp_path):
    calib = Calibration(ax=0.05, bx=14.0, ay=-0.03, by=55.0, iou=0.97)
    path = tmp_path / "PL.json"
    save_calibration(path, calib)
    assert load_calibration(path) == calib


def test_calibration_below_threshold_is_flagged():
    country = box(14.0, 49.0, 24.0, 55.0)
    cfg = load_config()
    min_iou = cfg.get("calibration.min_iou")
    with pytest.warns(UserWarning, match="calibration sous le seuil"):
        calib = fit_calibration(_cross_mask(), country, cfg)
    assert calib.iou < min_iou


def test_calibration_above_threshold_is_silent():
    country = box(14.0, 49.0, 24.0, 55.0)
    cfg = load_config()
    min_iou = cfg.get("calibration.min_iou")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        calib = fit_calibration(_rect_mask(), country, cfg)
    assert calib.iou >= min_iou
