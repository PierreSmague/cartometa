from __future__ import annotations
import math

import numpy as np
from scipy.ndimage import binary_closing, binary_opening
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from skimage.measure import find_contours, label, regionprops

from cartometa.config import Config
from cartometa.geo.calibrate import Calibration
from cartometa.geo.silhouette import Inset, red_pixels

EARTH_KM_PER_DEGREE = 111.32


def zone_mask(rgba: np.ndarray, inset: Inset, cfg: Config) -> np.ndarray:
    """Rouge retenu uniquement à l'intérieur de la silhouette du pays."""
    if inset is None:
        return np.zeros(rgba.shape[:2], dtype=bool)
    mask = red_pixels(rgba, cfg) & inset.mask
    structure = np.ones((3, 3))
    return binary_closing(binary_opening(mask, structure), structure)


def buffer_km(geom: BaseGeometry, km: float) -> BaseGeometry:
    """Dilatation d'environ `km`, en approximant localement le degré.

    Le buffer shapely est isotrope en degrés : un même nombre de degrés
    déplace la frontière de `degrees * EARTH_KM_PER_DEGREE` km en latitude,
    mais seulement `degrees * EARTH_KM_PER_DEGREE * cos(lat)` km en longitude
    (le degré de longitude se rétrécit avec la latitude). On choisit donc
    `degrees` pour garantir *au moins* `km` dans la direction la plus
    défavorable (la longitude) : à la latitude polonaise (~52°N, cos ≈ 0.616),
    un buffer demandé à 3 km vaut exactement 3,00 km en longitude mais environ
    4,87 km en latitude (facteur ~1,62). Cette sur-dilatation en latitude est
    délibérée et sans risque : la règle du projet est qu'un polygone trop
    large est préférable à un trop étroit (une méta manquante pénalise plus
    le joueur qu'une méta affichée à tort), et l'écart reste très inférieur
    au budget de 10 km.
    """
    if km <= 0:
        return geom
    centre_lat = geom.centroid.y
    degrees = km / (EARTH_KM_PER_DEGREE * max(math.cos(math.radians(centre_lat)), 0.1))
    return geom.buffer(degrees)


def mask_to_geometry(mask: np.ndarray, calib: Calibration, cfg: Config) -> BaseGeometry | None:
    labelled = label(mask)
    minimum = cfg.get("vectorize.min_component_px")
    tolerance = cfg.get("vectorize.simplify_tolerance_px")

    polygons: list[Polygon] = []
    for region in regionprops(labelled):
        if region.area < minimum:
            continue
        component = labelled == region.label
        # Marching squares sur le masque rembourré, pour fermer les formes au bord.
        padded = np.pad(component, 1, constant_values=False)
        for contour in find_contours(padded.astype(float), 0.5):
            if len(contour) < 4:
                continue
            pixels = [(x - 1, y - 1) for y, x in contour]
            ring = [calib.pixel_to_lonlat(x, y) for x, y in pixels]
            # NOTE (choix assumé) : `find_contours` peut renvoyer, pour une
            # même composante, à la fois le contour extérieur et le contour
            # d'un éventuel trou intérieur. Chaque contour est ici transformé
            # en polygone plein (pas en anneau intérieur), donc un trou serait
            # rebouché plutôt que représenté creux. C'est délibéré : la règle
            # du projet est qu'un polygone trop large vaut mieux qu'un trop
            # étroit (une méta manquante pénalise plus le joueur qu'une méta
            # affichée à tort), et un trou dans la zone rouge n'a de toute
            # façon aucune raison géographique d'être exclu du polygone final.
            polygon = Polygon(ring)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if polygon.is_empty:
                continue
            # NOTE : la tolérance (en pixels) n'est convertie qu'avec `ax`
            # (degrés de longitude par pixel). Comme `ay` diffère (distorsion
            # latitude/longitude), la tolérance réellement appliquée est
            # implicitement ~60 % plus large en direction des latitudes qu'en
            # longitude à la calibration Pologne (|ay|/|ax| ≈ 0.624, donc la
            # simplification, dimensionnée sur `ax`, autorise un écart d'arc
            # d'environ 1,2 km de plus le long des méridiens). Sans risque ici
            # aussi : ça va dans le sens "trop large plutôt que trop étroit",
            # et le budget de 10 km n'est pas approché.
            simplified = polygon.simplify(tolerance * abs(calib.ax), preserve_topology=True)
            if not simplified.is_empty and simplified.area > 0:
                polygons.append(simplified)

    if not polygons:
        return None

    merged = unary_union(polygons)
    if not merged.is_valid:
        merged = merged.buffer(0)
    merged = buffer_km(merged, cfg.get("vectorize.outward_buffer_km"))
    if merged.is_empty:
        return None
    if merged.geom_type == "GeometryCollection":
        parts = [g for g in merged.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        merged = unary_union(parts) if parts else None
    return merged
