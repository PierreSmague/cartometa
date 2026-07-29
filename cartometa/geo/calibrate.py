from __future__ import annotations
import json
import warnings
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
    # Provenance et contexte du fit retenu — valeurs par défaut pour rester
    # compatible avec les fichiers de calibration écrits avant leur ajout.
    visible: float = 1.0   # fraction du pays dans le cadre de l'image (edge_aware)
    variant: str = "largest"  # variante de silhouette utilisée (cf. inset_variants)
    meta_id: str = ""      # méta dont l'image a servi à calibrer

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


def _project_mask(mask: np.ndarray, calib_params, lon_grid, lat_grid):
    """Grille du masque projeté + cellules dont le pixel source est dans l'image.

    Rasterisation en sens inverse ("pull") : voir la note de _mask_to_grid.
    Le second tableau permet au mode edge_aware de fit_calibration de
    distinguer « le pays n'est pas là » (pixel lisible, vide) de « on ne
    sait pas » (pixel hors du cadre de l'image, carte rognée).
    """
    ax, bx, ay, by = calib_params
    xs = (lon_grid - bx) / ax
    ys = (lat_grid - by) / ay
    height, width = mask.shape
    cols = np.round(xs).astype(int)
    rows = np.round(ys).astype(int)
    inbounds = (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
    grid = np.zeros(lon_grid.shape, dtype=bool)
    grid[inbounds] = mask[rows[inbounds], cols[inbounds]]
    return grid, inbounds


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
    min_lon, min_lat, max_lon, max_lat = bounds
    lons = np.linspace(min_lon, max_lon, size)
    lats = np.linspace(max_lat, min_lat, size)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    grid, _ = _project_mask(mask, calib_params, lon_grid, lat_grid)
    return grid


def fit_calibration(
    mask: np.ndarray,
    country: BaseGeometry,
    cfg: Config,
    *,
    edge_aware: bool = False,
    warn: bool = True,
) -> Calibration:
    """Ajuste la transformation affine pixel → lon/lat maximisant l'IoU.

    `edge_aware` : pour une carte rognée par le cadrage de la capture
    (silhouette touchant le bord physique de l'image — Namibie, Inde
    mesurées), les cellules du pays qui retombent hors du cadre ne sont ni
    comptées comme manquées ni comme couvertes : on ne sait simplement pas.
    L'IoU est alors calculé sur la seule partie visible. Garde-fou : un
    alignement qui ne laisserait visible que moins de
    `calibration.edge_visible_min` du pays est rejeté (score nul) — sans ce
    plancher, l'optimiseur triche en poussant le pays hors cadre pour ne
    garder qu'un petit fragment bien aligné (optima dégénérés mesurés à
    35 % de pays visible).

    `warn` : émettre l'avertissement sous `calibration.min_iou`. À
    désactiver quand l'appelant compare plusieurs candidats et n'avertit
    que sur le fit finalement retenu.
    """
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
    target_total = max(int(target.sum()), 1)
    lons = np.linspace(min_lon, max_lon, RASTER_SIZE)
    lats = np.linspace(max_lat, min_lat, RASTER_SIZE)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    visible_min = cfg.get("calibration.edge_visible_min", 0.75)

    def negative_iou(params) -> float:
        grid, inbounds = _project_mask(mask, params, lon_grid, lat_grid)
        if edge_aware:
            if (target & inbounds).sum() / target_total < visible_min:
                return 0.0
            union = ((grid | target) & inbounds).sum()
            inter = (grid & target & inbounds).sum()
        else:
            union = (grid | target).sum()
            inter = (grid & target).sum()
        return 0.0 if union == 0 else -(inter / union)

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

    # Départs multiples en mode edge_aware : l'alignement des bounding boxes
    # écrase le pays entier dans le cadre, un optimum local assez fort pour
    # que Nelder-Mead n'en sorte jamais (mesuré : le fit edge_aware convergeait
    # exactement sur le fit standard). On repart donc aussi d'hypothèses où la
    # carte continue au-delà des bords touchés, en ancrant le côté intact.
    starts = [start]
    if edge_aware:
        starts.extend(_stretched_starts(mask, start, country.bounds))

    best_params, best_value = start, negative_iou(start)
    for candidate_start in starts:
        deltas = np.array([
            candidate_start[0] * step_rel, lon_span * step_rel * 0.5,
            candidate_start[2] * step_rel, lat_span * step_rel * 0.5,
        ])
        initial_simplex = np.vstack(
            [candidate_start] + [candidate_start + np.eye(4)[i] * deltas[i] for i in range(4)]
        )
        result = minimize(
            negative_iou, candidate_start, method="Nelder-Mead",
            options={
                "xatol": 1e-6, "fatol": 1e-4, "maxiter": 600,
                "initial_simplex": initial_simplex,
            },
        )
        for params_candidate in (result.x, candidate_start):
            value = negative_iou(params_candidate)
            if value < best_value:
                best_params, best_value = params_candidate, value
    params = best_params
    iou = float(-best_value)
    _, inbounds = _project_mask(mask, params, lon_grid, lat_grid)
    visible = float((target & inbounds).sum() / target_total)

    calib = Calibration(
        ax=float(params[0]), bx=float(params[1]),
        ay=float(params[2]), by=float(params[3]),
        iou=iou, visible=visible,
    )
    if warn:
        warn_if_below_threshold(calib, cfg)
    return calib


def _stretched_starts(mask: np.ndarray, start: np.ndarray, bounds) -> list[np.ndarray]:
    """Départs supplémentaires pour une carte rognée par le cadre de l'image.

    Quand la silhouette touche un bord, l'échelle déduite des bounding boxes
    est trop grande sur cet axe (le pays réel continue au-delà du cadre). On
    propose des échelles réduites (le pays « dépasse » de 15 % puis 22 % —
    au-delà, le plancher calibration.edge_visible_min rendrait le départ
    inévaluable), ancrées sur le bord intact : si la carte est coupée à
    droite, le bord gauche du masque reste fiable, et réciproquement.
    """
    ax, bx, ay, by = start
    min_lon, min_lat, max_lon, max_lat = bounds
    ys, xs = np.nonzero(mask)
    px0, px1 = xs.min(), xs.max()
    py0, py1 = ys.min(), ys.max()
    top, bottom = bool(mask[0].any()), bool(mask[-1].any())
    left, right = bool(mask[:, 0].any()), bool(mask[:, -1].any())

    factors = (0.85, 0.78)
    x_options = [(ax, bx)]
    if left or right:
        for factor in factors:
            ax2 = ax * factor
            if right and not left:
                bx2 = min_lon - ax2 * px0
            elif left and not right:
                bx2 = max_lon - ax2 * px1
            else:
                bx2 = (min_lon + max_lon) / 2 - ax2 * (px0 + px1) / 2
            x_options.append((ax2, bx2))
    y_options = [(ay, by)]
    if top or bottom:
        for factor in factors:
            ay2 = ay * factor
            if bottom and not top:
                by2 = max_lat - ay2 * py0
            elif top and not bottom:
                by2 = min_lat - ay2 * py1
            else:
                by2 = (max_lat + min_lat) / 2 - ay2 * (py0 + py1) / 2
            y_options.append((ay2, by2))

    combos = [
        np.array([ax_c, bx_c, ay_c, by_c])
        for ax_c, bx_c in x_options
        for ay_c, by_c in y_options
    ]
    return combos[1:]  # le premier est le départ standard, déjà couvert


def warn_if_below_threshold(calib: Calibration, cfg: Config) -> None:
    min_iou = cfg.get("calibration.min_iou", 0.0)
    if calib.iou < min_iou:
        warnings.warn(
            f"calibration sous le seuil requis : IoU={calib.iou:.4f} < "
            f"calibration.min_iou={min_iou:.4f} — pays à signaler, pas à "
            "traiter silencieusement.",
            stacklevel=2,
        )


def save_calibration(path: Path, calib: Calibration) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calib.to_dict(), indent=2), "utf-8")


def load_calibration(path: Path) -> Calibration:
    return Calibration.from_dict(json.loads(path.read_text("utf-8")))
