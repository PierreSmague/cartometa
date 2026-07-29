from __future__ import annotations
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import binary_closing, binary_fill_holes, binary_opening
from skimage.measure import label, regionprops

from cartometa.config import Config


@dataclass(frozen=True)
class Inset:
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1
    mask: np.ndarray                 # booléen, pleine taille image
    area_fraction: float


def red_pixels(rgba: np.ndarray, cfg: Config) -> np.ndarray:
    """Masque du rouge de la palette Plonk It, avec wrap-around de la teinte."""
    rgb = rgba[..., :3].astype(np.float64) / 255.0
    alpha = rgba[..., 3]
    maximum = rgb.max(axis=2)
    minimum = rgb.min(axis=2)
    delta = maximum - minimum

    with np.errstate(divide="ignore", invalid="ignore"):
        hue = np.zeros_like(maximum)
        red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        mask_r = (maximum == red) & (delta > 0)
        mask_g = (maximum == green) & (delta > 0)
        mask_b = (maximum == blue) & (delta > 0)
        hue[mask_r] = ((green - blue)[mask_r] / delta[mask_r]) % 6
        hue[mask_g] = ((blue - red)[mask_g] / delta[mask_g]) + 2
        hue[mask_b] = ((red - green)[mask_b] / delta[mask_b]) + 4
        hue = hue * 60.0
        saturation = np.where(maximum > 0, delta / np.maximum(maximum, 1e-9), 0.0)

    hue_min = cfg.get("red.hue_min")
    hue_max = cfg.get("red.hue_max")
    # Wrap-around : [340, 365] couvre 340→360 puis 0→5.
    in_hue = (hue >= hue_min) | (hue <= (hue_max - 360.0))
    return (
        in_hue
        & (saturation >= cfg.get("red.saturation_min"))
        & (maximum >= cfg.get("red.value_min"))
        & (alpha > 200)
    )


def _cream_pixels(rgba: np.ndarray, cfg: Config) -> np.ndarray:
    cream = np.array(cfg.get("cream.rgb"), dtype=np.int64)
    tolerance = cfg.get("cream.tolerance")
    diff = np.abs(rgba[..., :3].astype(np.int64) - cream).max(axis=2)
    return (diff <= tolerance) & (rgba[..., 3] > 200)


def find_inset(rgba: np.ndarray, cfg: Config) -> Inset | None:
    """Localise la silhouette du pays. Retourne None si l'image n'a pas d'encart."""
    height, width = rgba.shape[:2]
    candidate = _cream_pixels(rgba, cfg) | red_pixels(rgba, cfg)

    # Élimine le bruit poivre-et-sel (faux positifs isolés dans la photo) avant
    # la fermeture, sans quoi la fermeture les fusionne en un unique gros blob.
    opening_size = int(cfg.get("silhouette.opening_size"))
    candidate = binary_opening(candidate, np.ones((opening_size, opening_size)))

    size = int(cfg.get("silhouette.closing_size"))
    candidate = binary_closing(candidate, np.ones((size, size)))

    labelled = label(candidate)
    regions = [r for r in regionprops(labelled) if r.area >= cfg.get("silhouette.min_component_px")]
    if not regions:
        return None

    largest = max(regions, key=lambda r: r.area)
    area_fraction = largest.area / (width * height)
    if area_fraction < cfg.get("silhouette.min_area_fraction"):
        return None

    mask = binary_fill_holes(labelled == largest.label)
    y0, x0, y1, x1 = largest.bbox
    return Inset(bbox=(x0, y0, x1, y1), mask=mask, area_fraction=area_fraction)
