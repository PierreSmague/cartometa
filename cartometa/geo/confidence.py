from __future__ import annotations

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from cartometa.config import Config


def evaluate(
    geometry: BaseGeometry | None,
    *,
    tier: str,
    calib_iou: float | None,
    latlon: tuple[float, float] | None,
    component_count: int,
    touches_border: bool,
    area_fraction_of_country: float | None,
    cfg: Config,
) -> tuple[float, list[str]]:
    """Score dans [0, 1] servant uniquement à trier la file de revue."""
    warnings: list[str] = []

    if geometry is None or geometry.is_empty:
        return 0.0, ["aucune géométrie produite"]

    score = 1.0

    if calib_iou is not None and calib_iou < cfg.get("calibration.min_iou"):
        warnings.append(f"calibration faible (IoU {calib_iou:.2f})")
        score -= 0.3

    # Le contrôle le plus fort : le point Maps doit tomber dans le polygone.
    if latlon is not None and tier == "regional":
        if geometry.contains(Point(latlon[1], latlon[0])):
            score += 0.1
        else:
            warnings.append("le point Maps tombe hors du polygone")
            score -= 0.6

    if component_count > 5:
        warnings.append(f"{component_count} composantes disjointes, rouge parasite probable")
        score -= 0.2

    if touches_border:
        warnings.append("zone au bord de l'encart, possiblement tronquée")
        score -= 0.15

    if area_fraction_of_country is not None:
        if area_fraction_of_country > 0.95:
            warnings.append("rouge sur la quasi-totalité du pays, préférer le polygone national")
            score -= 0.25
        elif area_fraction_of_country < 0.002:
            warnings.append("surface très faible, île ou lieu ponctuel")
            score -= 0.1

    return max(0.0, min(1.0, score)), warnings
