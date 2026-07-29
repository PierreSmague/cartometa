from __future__ import annotations
import math

import numpy as np
from scipy.ndimage import binary_closing, binary_opening
from shapely.geometry import Polygon, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from skimage.measure import label, regionprops

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
    """Dilatation d'environ `km`, en approximant localement le degré."""
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
        from skimage.measure import find_contours

        padded = np.pad(component, 1, constant_values=False)
        for contour in find_contours(padded.astype(float), 0.5):
            if len(contour) < 4:
                continue
            pixels = [(x - 1, y - 1) for y, x in contour]
            ring = [calib.pixel_to_lonlat(x, y) for x, y in pixels]
            polygon = Polygon(ring)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if polygon.is_empty:
                continue
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
