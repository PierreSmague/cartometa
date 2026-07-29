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


def test_from_dict_accepts_files_written_before_provenance_fields():
    """Les fichiers data/calib/*.json existants n'ont que les 5 champs d'origine."""
    calib = Calibration.from_dict({"ax": 0.05, "bx": 14.0, "ay": -0.03, "by": 55.0, "iou": 0.97})
    assert calib.visible == 1.0
    assert calib.variant == "largest"
    assert calib.meta_id == ""


def test_warn_is_silenced_for_tournament_candidates():
    from cartometa.geo.calibrate import warn_if_below_threshold

    country = box(14.0, 49.0, 24.0, 55.0)
    cfg = load_config()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        calib = fit_calibration(_cross_mask(), country, cfg, warn=False)
    assert calib.iou < cfg.get("calibration.min_iou")
    with pytest.warns(UserWarning, match="calibration sous le seuil"):
        warn_if_below_threshold(calib, cfg)


def _l_country():
    """Un pays en L à branche basse fine : la forme pince l'échelle (contrairement
    à un rectangle) et l'écrasement dans le cadre coûte cher en IoU."""
    from shapely.ops import unary_union

    return unary_union([box(14.0, 49.0, 24.0, 50.5), box(14.0, 49.0, 17.0, 55.0)])


def _cropped_l_mask(width):
    """Le même L dessiné en pixels (ax=0.05, ay=-0.03, origine (100,50)),
    tronqué par un cadre d'image de largeur `width` : la branche basse
    déborderait jusqu'à x=300."""
    mask = np.zeros((300, width), dtype=bool)
    mask[200:250, 100:min(300, width)] = True  # branche basse (lat 49-50.5)
    mask[50:250, 100:160] = True               # colonne gauche (lon 14-17)
    return mask


def test_edge_aware_fit_ignores_country_parts_outside_the_frame():
    """Carte rognée par la capture (Namibie, Inde mesurées) : le fit standard
    écrase le pays dans le cadre, le fit edge_aware aligne la partie visible."""
    cfg = load_config()
    country = _l_country()
    mask = _cropped_l_mask(width=260)  # 2° de longitude hors cadre

    standard = fit_calibration(mask, country, cfg, warn=False)
    edge = fit_calibration(mask, country, cfg, edge_aware=True, warn=False)
    assert edge.iou > standard.iou + 0.02
    assert edge.iou > 0.9
    # La fraction visible reflète le rognage réel, sans passer sous le plancher.
    assert cfg.get("calibration.edge_visible_min") <= edge.visible < 0.97


def test_edge_aware_rejects_degenerate_mostly_hidden_alignments():
    """Garde-fou : sans plancher de visibilité, l'optimiseur pousse le pays
    hors cadre pour ne garder qu'un fragment bien aligné (optima dégénérés
    mesurés à 35 % de pays visible). Un cadrage qui cacherait plus de
    1 - edge_visible_min du pays ne doit jamais porter un score non nul :
    soit l'optimiseur retombe sur un alignement plus visible (score honnête),
    soit le score est nul."""
    cfg = load_config()
    country = _l_country()
    narrow = _cropped_l_mask(width=170)  # presque toute la branche basse hors cadre

    edge = fit_calibration(narrow, country, cfg, edge_aware=True, warn=False)
    assert edge.iou == 0.0 or edge.visible >= cfg.get("calibration.edge_visible_min")
