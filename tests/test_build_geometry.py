import math

import pytest

from cartometa.build.geometry import (
    DEFAULT_TOLERANCE,
    area_ratio,
    effective_tolerance,
    hausdorff,
    round_coordinates,
    simplify_geometry,
)


def _rectangle(x: float, y: float, largeur: float, hauteur: float, pas: int = 1) -> dict:
    """Rectangle dont les côtés portent `pas` sommets intermédiaires alignés.

    Les points intermédiaires sont exactement colinéaires : Douglas-Peucker
    doit les retirer quelle que soit la tolérance, ce qui donne un résultat
    prévisible sans dépendre des données réelles.
    """
    bas = [(x + largeur * i / pas, y) for i in range(pas)]
    droite = [(x + largeur, y + hauteur * i / pas) for i in range(pas)]
    haut = [(x + largeur - largeur * i / pas, y + hauteur) for i in range(pas)]
    gauche = [(x, y + hauteur - hauteur * i / pas) for i in range(pas)]
    anneau = bas + droite + haut + gauche
    anneau.append(anneau[0])
    return {"type": "Polygon", "coordinates": [[list(p) for p in anneau]]}


def test_l_arrondi_ramene_a_cinq_decimales():
    geometrie = {"type": "Polygon", "coordinates": [[
        [1.123456789, 2.987654321], [3.0, 2.0], [3.0, 4.0], [1.123456789, 2.987654321],
    ]]}

    arrondie = round_coordinates(geometrie)

    assert arrondie["coordinates"][0][0] == [1.12346, 2.98765]


def test_la_tolerance_est_plafonnee_par_la_taille_de_l_emprise():
    """Une emprise « spot » de 0,005° ne doit pas recevoir une tolérance de 0,01."""
    minuscule = _rectangle(35.51, 33.88, 0.005, 0.0035)

    tolerance = effective_tolerance(minuscule, DEFAULT_TOLERANCE)

    diagonale = math.hypot(0.005, 0.0035)
    assert tolerance == pytest.approx(diagonale / 50)
    assert tolerance < DEFAULT_TOLERANCE


def test_une_grande_emprise_recoit_la_tolerance_pleine():
    vaste = _rectangle(0.0, 0.0, 10.0, 10.0)

    assert effective_tolerance(vaste, DEFAULT_TOLERANCE) == DEFAULT_TOLERANCE


def test_la_simplification_retire_les_sommets_colineaires():
    dense = _rectangle(0.0, 0.0, 10.0, 10.0, pas=20)
    sommets_avant = len(dense["coordinates"][0])

    simplifiee = simplify_geometry(dense)

    assert len(simplifiee["coordinates"][0]) < sommets_avant


def test_la_simplification_preserve_l_aire_des_petites_emprises():
    """Le cas qui motive la tolérance adaptative : sans elle, on tombait à 24 %."""
    minuscule = _rectangle(35.51, 33.88, 0.005, 0.0035, pas=6)

    simplifiee = simplify_geometry(minuscule)

    assert area_ratio(minuscule, simplifiee) > 0.80


def test_la_simplification_ne_vide_jamais_une_geometrie():
    minuscule = _rectangle(35.51, 33.88, 0.0005, 0.0005, pas=4)

    simplifiee = simplify_geometry(minuscule)

    assert simplifiee["coordinates"][0]
    assert area_ratio(minuscule, simplifiee) > 0.0


def test_la_distance_de_hausdorff_reste_sous_la_tolerance_effective():
    dense = _rectangle(0.0, 0.0, 10.0, 10.0, pas=20)

    simplifiee = simplify_geometry(dense)

    assert hausdorff(dense, simplifiee) <= DEFAULT_TOLERANCE * 2


def test_un_multipolygone_est_simplifie_partie_par_partie():
    # `["coordinates"]` d'un Polygon est déjà une liste d'anneaux (ici un
    # seul, l'extérieur) : c'est la forme attendue pour un élément de
    # MultiPolygon. Indexer `[0]` donnerait l'anneau nu, sans ce niveau
    # d'imbrication, et `shape()` ne saurait plus le lire.
    multi = {"type": "MultiPolygon", "coordinates": [
        _rectangle(0.0, 0.0, 5.0, 5.0, pas=10)["coordinates"],
        _rectangle(20.0, 20.0, 5.0, 5.0, pas=10)["coordinates"],
    ]}

    simplifiee = simplify_geometry(multi)

    assert simplifiee["type"] == "MultiPolygon"
    assert len(simplifiee["coordinates"]) == 2
