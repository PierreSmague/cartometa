import math

import pytest
from shapely.geometry import Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry

from cartometa.build.geometry import (
    DEFAULT_TOLERANCE,
    SIZE_DIVISOR,
    area_ratio,
    effective_tolerance,
    hausdorff,
    part_bboxes,
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
    assert tolerance == pytest.approx(diagonale / SIZE_DIVISOR)
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


def test_la_simplification_ne_vide_jamais_une_geometrie(monkeypatch):
    """Le filet de sécurité contre la dégénérescence, exercé pour de vrai.

    Avec `preserve_topology=True`, GEOS ne produit jamais de résultat vide ou
    invalide sur une entrée saine — même une emprise « spot » minuscule ou un
    anneau extrêmement fin survit intact (vérifié empiriquement : aucune
    combinaison de taille ni de tolérance ne suffit à le faire dégénérer). Le
    filet ne protège donc que contre une pathologie que ni la géométrie
    d'origine ni la tolérance ne peuvent provoquer ici ; on la simule pour de
    vrai, en forçant GEOS à renvoyer une géométrie vide, comme il pourrait le
    faire sur des données de terrain vraiment tordues.
    """
    geometrie = _rectangle(35.51, 33.88, 0.005, 0.0035, pas=6)

    def simplification_degeneree(self, tolerance, preserve_topology=True):
        return Polygon()

    monkeypatch.setattr(BaseGeometry, "simplify", simplification_degeneree)

    simplifiee = simplify_geometry(geometrie)

    assert simplifiee["coordinates"][0]
    assert area_ratio(geometrie, simplifiee) == pytest.approx(1.0)


def test_le_repli_arrondit_l_original_quand_l_arrondi_de_la_simplification_degenere(
    monkeypatch,
):
    """La validité doit être vérifiée sur le résultat arrondi, pas avant.

    Mécanisme réel derrière `VN:s59g` : Douglas-Peucker (avec
    `preserve_topology=True`) renvoie ici un résultat valide et de surface
    non nulle, mais dont deux sommets sont si proches (moins de 1e-5°) que
    l'arrondi à 5 décimales les confond, faisant s'effondrer l'anneau sur un
    unique point. Vérifier `simplifiee` (avant arrondi) le laisserait passer
    tel quel ; c'est `round_coordinates(mapping(simplifiee))` qui doit être
    invalidé pour déclencher le repli sur l'original arrondi — lui indemne
    puisqu'il ne partage aucun sommet avec la géométrie simplifiée.
    """
    original = _rectangle(0.0, 0.0, 10.0, 10.0, pas=4)

    degenere_a_l_arrondi = Polygon(
        [(0.0, 0.0), (0.000002, 0.0), (0.000001, 0.000002), (0.0, 0.0)]
    )
    assert degenere_a_l_arrondi.is_valid and degenere_a_l_arrondi.area > 0
    # Sanity : c'est bien l'arrondi, et non `degenere_a_l_arrondi` elle-même,
    # qui casse — sans quoi ce test ne prouverait rien sur le nouvel ordre.
    arrondie = shape(round_coordinates(mapping(degenere_a_l_arrondi)))
    assert arrondie.is_empty or not arrondie.is_valid or arrondie.area == 0

    def simplification_qui_degenere_a_l_arrondi(self, tolerance, preserve_topology=True):
        return degenere_a_l_arrondi

    monkeypatch.setattr(BaseGeometry, "simplify", simplification_qui_degenere_a_l_arrondi)

    resultat = simplify_geometry(original)

    assert shape(resultat).is_valid
    assert resultat == round_coordinates(original)


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


def _multi(*rectangles: dict) -> dict:
    return {"type": "MultiPolygon",
            "coordinates": [r["coordinates"] for r in rectangles]}


def test_un_polygone_donne_une_seule_bbox_egale_a_ses_bornes():
    geometrie = _rectangle(2.0, 48.0, 3.0, 1.0)

    assert part_bboxes(geometrie) == [(2.0, 48.0, 5.0, 49.0)]


def test_les_parties_de_part_et_d_autre_de_l_antimeridien_gardent_leurs_bbox():
    """Le cas russe : une emprise nationale à cheval sur ±180° a pour bbox
    globale -180…180, qui recouvre tout l'hémisphère nord — un clic à Londres
    téléchargeait les 8,3 Mo de la Russie pour rien. Par partie, aucune boîte
    ne traverse le méridien et le préfiltre redevient discriminant."""
    geometrie = _multi(
        _rectangle(170.0, 55.0, 9.0, 10.0),
        _rectangle(-179.0, 55.0, 9.0, 10.0),
    )

    boites = part_bboxes(geometrie)

    assert len(boites) == 2
    assert all(max_lon - min_lon < 30 for min_lon, _, max_lon, _ in boites)


def test_une_ile_lointaine_garde_sa_propre_bbox():
    """Le cas norvégien : Bouvet, à -54° de latitude, étirait la bbox du pays
    sur 135° de latitude. L'île doit rester dans sa propre boîte."""
    continent = [_rectangle(5.0 + i, 58.0, 0.8, 0.8) for i in range(5)]
    bouvet = _rectangle(3.0, -54.5, 0.5, 0.5)

    boites = part_bboxes(_multi(*continent, bouvet))

    assert (3.0, -54.5, 3.5, -54.0) in boites
    assert all(max_lat - min_lat < 30 for _, min_lat, _, max_lat in boites)


def test_le_nombre_de_boites_est_plafonne_et_tout_est_couvert():
    """Un contour national compte des centaines d'îles : une boîte par île
    ferait exploser l'index. Au plafond, chaque partie doit rester couverte
    par au moins une boîte."""
    parties = [_rectangle(float(i * 7), float((i * 13) % 50), 1.0, 1.0) for i in range(40)]

    boites = part_bboxes(_multi(*parties), max_boxes=4)

    assert len(boites) <= 4
    for partie in parties:
        min_lon, min_lat, max_lon, max_lat = shape(partie).bounds
        assert any(
            b[0] <= min_lon and b[1] <= min_lat and b[2] >= max_lon and b[3] >= max_lat
            for b in boites
        )
