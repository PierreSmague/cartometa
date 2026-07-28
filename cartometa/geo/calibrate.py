from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from shapely.geometry.base import BaseGeometry

from cartometa.config import Config

RASTER_SIZE = 220  # grille de comparaison ; assez fin pour l'IoU, assez rapide


@dataclass(frozen=True)
class Calibration:
    ax: float
    bx: float
    ay: float
    by: float
    iou: float

    def pixel_to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        return (self.ax * x + self.bx, self.ay * y + self.by)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Calibration":
        return Calibration(**data)


def _rasterize(geom: BaseGeometry, bounds, size: int) -> np.ndarray:
    """Rasterise une géométrie dans une grille size×size couvrant `bounds`."""
    from shapely import contains_xy

    min_lon, min_lat, max_lon, max_lat = bounds
    lons = np.linspace(min_lon, max_lon, size)
    lats = np.linspace(max_lat, min_lat, size)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    grid = contains_xy(geom, lon_grid, lat_grid)
    return grid


def _mask_to_grid(mask: np.ndarray, calib_params, bounds, size: int) -> np.ndarray:
    """Projette le masque pixel dans la même grille géographique.

    NOTE (correction) : le brief proposait une projection "aller" - pour
    chaque pixel non nul du masque, calculer sa position dans la grille
    géographique et l'y marquer. Ce scatter aller laisse des trous dès que
    l'étendue en pixels du masque ne coïncide pas exactement avec `size`
    (ce qui est presque toujours le cas) : plusieurs pixels sources peuvent
    retomber sur la même cellule de la grille cible tandis que d'autres
    cellules ne reçoivent aucun pixel source, créant des vides artificiels
    qui font chuter l'IoU même pour un rectangle parfaitement aligné (mesuré :
    0.811 au lieu de ~0.98 sur le test synthétique). On rasterise donc plutôt
    en sens inverse ("pull" / requête) : pour chaque cellule de la grille
    géographique cible, on retrouve le pixel source correspondant par la
    transformation inverse et on lit sa valeur dans le masque. Chaque cellule
    de la grille reçoit ainsi toujours une réponse, sans trou.
    """
    ax, bx, ay, by = calib_params
    min_lon, min_lat, max_lon, max_lat = bounds
    lons = np.linspace(min_lon, max_lon, size)
    lats = np.linspace(max_lat, min_lat, size)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    xs = (lon_grid - bx) / ax
    ys = (lat_grid - by) / ay
    height, width = mask.shape
    cols = np.round(xs).astype(int)
    rows = np.round(ys).astype(int)
    keep = (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
    grid = np.zeros((size, size), dtype=bool)
    grid[keep] = mask[rows[keep], cols[keep]]
    return grid


def fit_calibration(mask: np.ndarray, country: BaseGeometry, cfg: Config) -> Calibration:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        raise ValueError("silhouette vide, calibration impossible")

    px0, px1 = xs.min(), xs.max()
    py0, py1 = ys.min(), ys.max()
    min_lon, min_lat, max_lon, max_lat = country.bounds

    # Départ : alignement des bounding boxes.
    ax = (max_lon - min_lon) / max(px1 - px0, 1)
    ay = -(max_lat - min_lat) / max(py1 - py0, 1)
    start = np.array([ax, min_lon - ax * px0, ay, max_lat - ay * py0])

    bounds = country.bounds
    target = _rasterize(country, bounds, RASTER_SIZE)

    def negative_iou(params) -> float:
        grid = _mask_to_grid(mask, params, bounds, RASTER_SIZE)
        union = (grid | target).sum()
        return 0.0 if union == 0 else -((grid & target).sum() / union)

    # Simplex initial construit à la main (correction) : scipy dérive par
    # défaut la taille du simplexe initial d'un pourcentage relatif (5 %) de
    # chaque paramètre. Or ax/ay (≈0.03-0.05) et bx/by (≈10-56) vivent à des
    # échelles très différentes : un pas de 5 % sur bx/by déplace le point de
    # départ de plusieurs dixièmes de degré d'un coup, bien plus que ce que
    # justifie un raffinement local. Sur le test synthétique (rectangle
    # parfaitement alignable), ce déséquilibre faisait dériver Nelder-Mead
    # vers un optimum à peine meilleur en IoU (+0.004) mais décalé de
    # 0,25° en coin — largement hors tolérance. On fournit donc un simplexe
    # initial dont chaque pas est calibré sur l'échelle géographique réelle
    # (une fraction de l'étendue du pays), identique pour ax/bx et ay/by.
    lon_span = max_lon - min_lon
    lat_span = max_lat - min_lat
    step_rel = 0.008
    deltas = np.array([
        start[0] * step_rel, lon_span * step_rel * 0.5,
        start[2] * step_rel, lat_span * step_rel * 0.5,
    ])
    initial_simplex = np.vstack(
        [start] + [start + np.eye(4)[i] * deltas[i] for i in range(4)]
    )
    result = minimize(
        negative_iou, start, method="Nelder-Mead",
        options={
            "xatol": 1e-6, "fatol": 1e-4, "maxiter": 600,
            "initial_simplex": initial_simplex,
        },
    )
    params = result.x if -result.fun >= -negative_iou(start) else start
    return Calibration(
        ax=float(params[0]), bx=float(params[1]),
        ay=float(params[2]), by=float(params[3]),
        iou=float(-negative_iou(params)),
    )


def save_calibration(path: Path, calib: Calibration) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calib.to_dict(), indent=2), "utf-8")


def load_calibration(path: Path) -> Calibration:
    return Calibration.from_dict(json.loads(path.read_text("utf-8")))
