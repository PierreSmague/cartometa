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
    variant: str = "largest"         # "largest" ou "multi" (cf. inset_variants)


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


def _significant_regions(rgba: np.ndarray, cfg: Config):
    candidate = _cream_pixels(rgba, cfg) | red_pixels(rgba, cfg)

    # Élimine le bruit poivre-et-sel (faux positifs isolés dans la photo) avant
    # la fermeture, sans quoi la fermeture les fusionne en un unique gros blob.
    opening_size = int(cfg.get("silhouette.opening_size"))
    candidate = binary_opening(candidate, np.ones((opening_size, opening_size)))

    size = int(cfg.get("silhouette.closing_size"))
    candidate = binary_closing(candidate, np.ones((size, size)))

    labelled = label(candidate)
    regions = [r for r in regionprops(labelled) if r.area >= cfg.get("silhouette.min_component_px")]
    return labelled, regions


def inset_variants(rgba: np.ndarray, cfg: Config) -> list[Inset]:
    """Les silhouettes candidates d'une image, plus grande composante d'abord.

    La plus grande composante suffit pour un pays d'un seul tenant, mais
    réduit un archipel à sa plus grande île (Hong Kong mesuré à IoU 0,56
    contre 0,80 en gardant toutes les îles). On propose donc aussi, quand
    elles existent, l'union des composantes pesant au moins
    `calibration.multi_min_fraction` de la plus grande — le seuil écarte le
    bruit résiduel de la photo sans écarter les vraies îles. L'appelant
    départage les variantes par l'IoU de calibration : aucune règle a priori
    ne décide si les composantes secondaires sont des îles (Hong Kong) ou
    des parasites (encart décoratif de l'Inde).
    """
    height, width = rgba.shape[:2]
    labelled, regions = _significant_regions(rgba, cfg)
    if not regions:
        return []

    biggest = max(regions, key=lambda r: r.area)
    area_fraction = biggest.area / (width * height)
    if area_fraction < cfg.get("silhouette.min_area_fraction"):
        return []

    mask = binary_fill_holes(labelled == biggest.label)
    y0, x0, y1, x1 = biggest.bbox
    largest = Inset(bbox=(x0, y0, x1, y1), mask=mask, area_fraction=area_fraction)

    threshold = cfg.get("calibration.multi_min_fraction", 0.02) * biggest.area
    kept = [r for r in regions if r.area >= threshold]
    if len(kept) < 2:
        return [largest]

    union = np.zeros(labelled.shape, dtype=bool)
    for region in kept:
        union |= labelled == region.label
    union = binary_fill_holes(union)
    ys, xs = np.nonzero(union)
    multi = Inset(
        bbox=(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
        mask=union,
        area_fraction=union.sum() / (width * height),
        variant="multi",
    )
    return [largest, multi]


def find_inset(rgba: np.ndarray, cfg: Config) -> Inset | None:
    """Localise la silhouette du pays (plus grande composante).

    Conservée comme raccourci historique ; `inset_variants` expose aussi la
    variante multi-composantes pour les archipels.
    """
    variants = inset_variants(rgba, cfg)
    return variants[0] if variants else None


def touches_image_edge(mask: np.ndarray) -> bool:
    """Vrai si la silhouette touche le bord physique de l'image.

    C'est le signe d'une carte rognée par le cadrage de la capture (Namibie,
    Inde mesurées) : la partie du pays hors cadre ne doit alors pas compter
    contre l'alignement de calibration (cf. fit_calibration edge_aware).
    """
    return bool(mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any())
