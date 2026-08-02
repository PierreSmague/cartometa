from __future__ import annotations

import math
from typing import Any

from shapely.geometry import mapping, shape
from shapely.ops import transform

# ~1,1 km à l'équateur. Invisible sur une emprise du type « ce poteau se
# trouve dans cette région », qui est ce que décrivent les métas.
DEFAULT_TOLERANCE = 0.01
# ~1 m. En deçà, on stocke du bruit de flottant.
COORD_PRECISION = 5
# La tolérance ne dépasse jamais la diagonale de l'emprise divisée par ce
# nombre. Sans ce plafond, une tolérance fixe de 0,01° est plus grande que
# les emprises « spot » (~0,005° de côté) et les ampute : mesuré sur les
# données réelles, la pire n'en gardait que 24 % de sa surface.
SIZE_DIVISOR = 50


def _en_listes(valeur: Any) -> Any:
    """Convertit récursivement les tuples de `mapping()` en listes.

    Shapely renvoie des coordonnées en tuples immuables ; le reste du code
    (ex. `GeoRecord.geometry`, la sérialisation JSON des exports) attend des
    listes, comme dans les fichiers GeoJSON sur disque.
    """
    if isinstance(valeur, (tuple, list)):
        return [_en_listes(v) for v in valeur]
    return valeur


def round_coordinates(geometry: dict, precision: int = COORD_PRECISION) -> dict:
    """Arrondit toutes les coordonnées, sans toucher à la topologie."""
    arrondi = transform(
        lambda x, y, z=None: (round(x, precision), round(y, precision)),
        shape(geometry),
    )
    resultat = mapping(arrondi)
    return {**resultat, "coordinates": _en_listes(resultat["coordinates"])}


def effective_tolerance(
    geometry: dict, tolerance: float, divisor: int = SIZE_DIVISOR
) -> float:
    """Tolérance plafonnée par la taille propre de l'emprise."""
    min_lon, min_lat, max_lon, max_lat = shape(geometry).bounds
    diagonale = math.hypot(max_lon - min_lon, max_lat - min_lat)
    return min(tolerance, diagonale / divisor)


def simplify_geometry(
    geometry: dict,
    tolerance: float = DEFAULT_TOLERANCE,
    precision: int = COORD_PRECISION,
) -> dict:
    """Simplifie puis arrondit.

    Dans cet ordre : arrondir d'abord ferait travailler Douglas-Peucker sur
    des sommets déjà déplacés. En cas de dégénérescence — géométrie vide ou
    invalide, ce que la simplification topologique peut produire sur des
    formes pathologiques — on retombe sur l'original arrondi plutôt que de
    publier une emprise fausse.
    """
    original = shape(geometry)
    simplifiee = original.simplify(
        effective_tolerance(geometry, tolerance), preserve_topology=True
    )
    if simplifiee.is_empty or not simplifiee.is_valid or simplifiee.area == 0:
        return round_coordinates(geometry, precision)
    return round_coordinates(mapping(simplifiee), precision)


def area_ratio(original: dict, simplified: dict) -> float:
    """Part de la surface conservée, entre 0 et 1 (au-delà si elle a grossi)."""
    aire = shape(original).area
    if aire == 0:
        return 1.0
    return shape(simplified).area / aire


def hausdorff(original: dict, simplified: dict) -> float:
    """Écart maximal entre les deux contours, en degrés."""
    return shape(original).hausdorff_distance(shape(simplified))
