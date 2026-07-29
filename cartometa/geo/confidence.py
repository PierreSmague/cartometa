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
        # NOTE (correction, relecture finale) : `touches_border` teste le bord
        # de la boîte englobante de la SILHOUETTE DU PAYS (`inset.bbox`), pas
        # le cadre de l'image composite. Toucher ce bord signifie seulement
        # « la zone atteint l'extrémité du pays » — parfaitement normal pour
        # une méta régionale frontalière, et mesuré chez 6 des 11 métas
        # régionales de la Pologne, dont des géométries par ailleurs justes.
        # Ce n'est donc PAS un signe fiable de troncature par le cadrage de
        # l'image (voir cartometa/geo/cli.py pour la tentative de mesure
        # directe sur le bord réel de l'image, abandonnée : les fermetures/
        # ouvertures morphologiques rendent ce bord non fiable). On se
        # contente donc de rapporter le fait observé, sans jugement de
        # troncature ni malus de confiance — il ne doit pas faire remonter
        # ces métas, par ailleurs correctes, en tête de la file de revue.
        warnings.append(
            "zone au contact du bord de la silhouette du pays détectée "
            "(fréquent et normal en bordure nationale, ne signifie pas "
            "que l'image est tronquée)"
        )

    if area_fraction_of_country is not None:
        if area_fraction_of_country > 0.95:
            warnings.append("rouge sur la quasi-totalité du pays, préférer le polygone national")
            score -= 0.25
        elif area_fraction_of_country < 0.002:
            warnings.append("surface très faible, île ou lieu ponctuel")
            score -= 0.1

    return max(0.0, min(1.0, score)), warnings
