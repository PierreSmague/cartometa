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
# données réelles, la pire n'en gardait que 24 % de sa surface. C'est ce
# plafond, et lui seul, qui empêche la tolérance fixe de détruire ces petites
# emprises.
#
# 500 est un choix mesuré, pas arbitraire : sur les 1 710 emprises réelles de
# `data/geo/`, faire varier ce diviseur donne (nombre d'emprises hors du
# seuil de dérive de surface / pire dérive / poids gzip total / poids du
# pays le plus lourd (ID)) :
#
#   50   (ancien) : 231 / 16,5 % / 2385 Ko / 854 Ko
#   200          :  73 /  3,8 % / 2398 Ko / 854 Ko
#   500 (retenu) :  19 /  3,3 % / 2443 Ko / 855 Ko
#   1000         :   6 /  3,0 % / 2610 Ko / 862 Ko
#   2000         :   2 /  0,9 % / 3330 Ko / 891 Ko
#   5000         :   0 /  0,2 % / 5198 Ko / 994 Ko
#
# 500 divise par cinq la pire dérive (16,5 % → 3,3 %) pour un surcoût d'à
# peine un kilo-octet sur le pays le plus lourd. Aller plus loin coûte cher
# sans annuler la dérive : à 5000, elle ne s'annule presque (0,2 %) qu'en
# amenant l'Indonésie à 994 Ko, à la limite du plafond d'1 Mo par pays de la
# spec §14 critère 3 — ce n'est donc pas la direction à suivre si ce chiffre
# doit encore monter. Si ce nombre est revu un jour, remesurer sur les
# données réelles plutôt que d'ajuster à vue : le compromis n'est pas
# monotone au-delà d'un certain point.
SIZE_DIVISOR = 500


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


def _degeneree(geometrie) -> bool:
    """Vide, invalide ou de surface nulle : rien qu'on veuille publier."""
    return geometrie.is_empty or not geometrie.is_valid or geometrie.area == 0


def simplify_geometry(
    geometry: dict,
    tolerance: float = DEFAULT_TOLERANCE,
    precision: int = COORD_PRECISION,
) -> dict:
    """Simplifie puis arrondit.

    Dans cet ordre : arrondir d'abord ferait travailler Douglas-Peucker sur
    des sommets déjà déplacés.

    La validité est vérifiée sur ce que la fonction s'apprête réellement à
    renvoyer, pas sur une étape intermédiaire : l'arrondi fait partie de la
    transformation, et arrondir à 5 décimales peut à lui seul faire passer un
    anneau sous le nombre minimal de points requis — un résultat de
    simplification valide peut donc redevenir invalide *après* l'arrondi.
    Vérifier `simplifiee` avant arrondi laisserait passer ce cas.

    Trois niveaux de repli, du meilleur au pire :
    1. simplifiée puis arrondie — le cas normal ;
    2. si ce résultat est dégénéré (vide, invalide ou de surface nulle) :
       l'original arrondi ;
    3. si l'original arrondi l'est aussi (l'arrondi seul peut en principe
       dégrader une entrée pathologique) : l'original tel quel, sans arrondi.
       Publier une emprise plus lourde mais exacte vaut toujours mieux que
       publier une géométrie invalide.
    """
    original = shape(geometry)
    simplifiee = original.simplify(
        effective_tolerance(geometry, tolerance), preserve_topology=True
    )
    candidat = round_coordinates(mapping(simplifiee), precision)
    if not _degeneree(shape(candidat)):
        return candidat

    candidat = round_coordinates(geometry, precision)
    if not _degeneree(shape(candidat)):
        return candidat

    return geometry


# Plafond de boîtes par emprise dans l'index. Quatre suffit aux cas réels qui
# motivent le découpage : la Russie à cheval sur ±180°, la Norvège avec Jan
# Mayen et Bouvet, les Pays-Bas avec les Caraïbes. Au-delà, chaque boîte
# supplémentaire n'affine presque plus le préfiltre mais grossit l'index pour
# toutes les emprises.
MAX_BBOXES = 4
# Au-delà de ce nombre de parties, la fusion gloutonne (quadratique) devient
# coûteuse : on pré-agrège d'abord les petites parties sur les plus grandes.
_SEUIL_PRE_AGREGATION = 32


def _aire_bbox(boite: tuple[float, float, float, float]) -> float:
    return (boite[2] - boite[0]) * (boite[3] - boite[1])


def _union_bbox(a, b) -> tuple[float, float, float, float]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def part_bboxes(
    geometry: dict, max_boxes: int = MAX_BBOXES
) -> list[tuple[float, float, float, float]]:
    """Bboxes couvrant l'emprise, une par groupe de parties proches.

    La bbox globale d'un multipolygone aux parties éloignées ne discrimine
    plus rien : celle de la Russie (à cheval sur l'antiméridien) couvre
    -180…180, celle de la Norvège descend à Bouvet par -54° de latitude. Le
    préfiltre du viewer téléchargeait alors des pays entiers pour des clics
    qui ne les concernent pas — 8,3 Mo de Russie pour un clic à Londres.

    Fusion gloutonne : tant qu'il reste trop de boîtes, fusionner les deux
    dont l'union gaspille le moins de surface. Les parties proches s'agrègent
    entre elles ; une île lointaine ne fusionne qu'en dernier recours, donc
    garde sa propre boîte tant que le plafond le permet. Toute partie reste
    couverte par construction — les boîtes ne font que grossir.
    """
    forme = shape(geometry)
    parties = list(forme.geoms) if hasattr(forme, "geoms") else [forme]
    boites = [partie.bounds for partie in parties]

    if len(boites) > _SEUIL_PRE_AGREGATION:
        # Les contours nationaux comptent des centaines d'îlots : la fusion
        # quadratique sur tous serait chère pour rien. On garde les plus
        # grandes boîtes comme graines et on agrège chaque îlot sur celle
        # qu'il fait le moins grossir.
        boites.sort(key=_aire_bbox, reverse=True)
        graines = boites[:_SEUIL_PRE_AGREGATION]
        for boite in boites[_SEUIL_PRE_AGREGATION:]:
            meilleure = min(
                range(len(graines)),
                key=lambda i: _aire_bbox(_union_bbox(graines[i], boite)) - _aire_bbox(graines[i]),
            )
            graines[meilleure] = _union_bbox(graines[meilleure], boite)
        boites = graines

    while len(boites) > max_boxes:
        gaspillage_minimal, paire = None, None
        for i in range(len(boites)):
            for j in range(i + 1, len(boites)):
                gaspillage = (
                    _aire_bbox(_union_bbox(boites[i], boites[j]))
                    - _aire_bbox(boites[i]) - _aire_bbox(boites[j])
                )
                if gaspillage_minimal is None or gaspillage < gaspillage_minimal:
                    gaspillage_minimal, paire = gaspillage, (i, j)
        i, j = paire
        boites[i] = _union_bbox(boites[i], boites[j])
        del boites[j]
    return boites


def area_ratio(original: dict, simplified: dict) -> float:
    """Part de la surface conservée, entre 0 et 1 (au-delà si elle a grossi)."""
    aire = shape(original).area
    if aire == 0:
        return 1.0
    return shape(simplified).area / aire


def hausdorff(original: dict, simplified: dict) -> float:
    """Écart maximal entre les deux contours, en degrés."""
    return shape(original).hausdorff_distance(shape(simplified))
