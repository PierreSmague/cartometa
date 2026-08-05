from __future__ import annotations

import math
from typing import Any

from shapely.geometry import mapping, shape
from shapely.ops import transform

# ~1.1 km at the equator. Invisible on a footprint of the "this pole is found
# in this region" kind, which is what the metas describe.
DEFAULT_TOLERANCE = 0.01
# ~1 m. Below that, we would be storing float noise.
COORD_PRECISION = 5
# The tolerance never exceeds the footprint's diagonal divided by this number.
# Without that cap, a fixed tolerance of 0.01° is larger than the "spot"
# footprints (~0.005° across) and amputates them: measured on the real data, the
# worst one kept only 24 % of its area. This cap, and it alone, is what stops
# the fixed tolerance from destroying those small footprints.
#
# 500 is a measured choice, not an arbitrary one: over the 1,710 real footprints
# in `data/geo/`, varying this divisor gives (number of footprints outside the
# area-drift threshold / worst drift / total gzip weight / weight of the
# heaviest country (ID)):
#
#   50   (former)  : 231 / 16.5 % / 2385 KB / 854 KB
#   200           :  73 /  3.8 % / 2398 KB / 854 KB
#   500 (chosen)  :  19 /  3.3 % / 2443 KB / 855 KB
#   1000          :   6 /  3.0 % / 2610 KB / 862 KB
#   2000          :   2 /  0.9 % / 3330 KB / 891 KB
#   5000          :   0 /  0.2 % / 5198 KB / 994 KB
#
# 500 divides the worst drift by five (16.5 % → 3.3 %) for barely a kilobyte of
# overhead on the heaviest country. Going further is expensive without cancelling
# the drift: at 5000 it only almost vanishes (0.2 %), and only by taking
# Indonesia to 994 KB, right at the 1 MB per country cap of spec §14 criterion 3
# — so that is not the direction to take if that figure still has to grow. If
# this number is ever revisited, re-measure on the real data rather than tuning
# by eye: the trade-off is not monotonic beyond a certain point.
SIZE_DIVISOR = 500

# A ribbon's diagonal says nothing about its width. The mean width
# 2*area/perimeter is the honest scale for thin shapes; dividing it by 50
# keeps the measured drift well under the 5 % promise. But this bound only
# *governs* (comes out as the smallest of the three candidates in
# `effective_tolerance`) for footprints whose mean width sits strictly between
# diagonal/40 and diagonal/10 (see THIN_FLOOR_DIVISOR below for the lower
# edge) — about 716 of the real footprints in `data/geo/`. Above that band
# (squares and blobs, mean width ~diagonal/3) the diagonal cap (SIZE_DIVISOR)
# already wins and this constant has no effect; below it (extreme ribbons,
# e.g. KG "WjWO") the width bound alone would be even finer, but the floor
# takes over instead — see THIN_FLOOR_DIVISOR for why that regression is
# actually fixed by the floor, not by this constant.
THIN_DIVISOR = 50

# Floor for the width bound: never finer than the footprint's diagonal / 2000.
# 2*area/perimeter collapses on fractal coastlines (fjords, archipelagos) whose
# perimeter is enormous — without this floor their simplification becomes a
# no-op, the hausdorff check grinds for minutes per footprint and the published
# weight of already-heavy countries (ID at 855 KB, spec cap 1 MB) balloons.
#
# This floor is also what actually saves the regression that started this
# work: KG "WjWO" (a 1.26° x 0.15° valley ribbon) has a mean width of only
# 0.0129° — well under diagonal/40 (~0.032°) — so the width bound alone
# (0.000259°) falls under the floor (0.000636°) and the floor wins the
# max(), giving a tolerance ~4x finer than the old diagonal/500 (0.00254°)
# and keeping WjWO's area drift under 5 %. THIN_DIVISOR above only matters
# for the intermediate band of footprints whose width bound lands between
# this floor and the diagonal cap.
#
# 2000 comes from the measured table above: worst drift 0.9 %, heaviest
# country still under the cap even if EVERY footprint used it — and here
# only the rough-perimeter ones fall back to it.
THIN_FLOOR_DIVISOR = 2000


def _en_listes(valeur: Any) -> Any:
    """Recursively convert the tuples from `mapping()` into lists.

    Shapely returns coordinates as immutable tuples; the rest of the code (e.g.
    `GeoRecord.geometry`, the JSON serialisation of the exports) expects lists,
    as in the GeoJSON files on disk.
    """
    if isinstance(valeur, (tuple, list)):
        return [_en_listes(v) for v in valeur]
    return valeur


def round_coordinates(geometry: dict, precision: int = COORD_PRECISION) -> dict:
    """Round every coordinate, without touching the topology."""
    arrondi = transform(
        lambda x, y, z=None: (round(x, precision), round(y, precision)),
        shape(geometry),
    )
    resultat = mapping(arrondi)
    return {**resultat, "coordinates": _en_listes(resultat["coordinates"])}


def effective_tolerance(
    geometry: dict, tolerance: float, divisor: int = SIZE_DIVISOR
) -> float:
    """Tolerance capped by the footprint's own size — and by its mean width,
    so that thin ribbons are not over-simplified."""
    forme = shape(geometry)
    min_lon, min_lat, max_lon, max_lat = forme.bounds
    diagonale = math.hypot(max_lon - min_lon, max_lat - min_lat)
    bornes = [tolerance, diagonale / divisor]
    if forme.length > 0:
        largeur_moyenne = 2.0 * forme.area / forme.length
        bornes.append(max(largeur_moyenne / THIN_DIVISOR, diagonale / THIN_FLOOR_DIVISOR))
    return min(bornes)


def _degeneree(geometrie) -> bool:
    """Empty, invalid or zero-area: nothing we would want to publish."""
    return geometrie.is_empty or not geometrie.is_valid or geometrie.area == 0


def simplify_geometry(
    geometry: dict,
    tolerance: float = DEFAULT_TOLERANCE,
    precision: int = COORD_PRECISION,
) -> dict:
    """Simplify, then round.

    In that order: rounding first would make Douglas-Peucker work on vertices
    that have already been moved.

    Validity is checked on what the function is actually about to return, not on
    an intermediate step: rounding is part of the transformation, and rounding to
    5 decimals can on its own take a ring below the minimum number of points
    required — so a valid simplification result can become invalid again *after*
    rounding. Checking `simplifiee` before rounding would let that case through.

    Three fallback levels, best to worst:
    1. simplified then rounded — the normal case;
    2. if that result is degenerate (empty, invalid or zero-area): the rounded
       original;
    3. if the rounded original is degenerate too (rounding alone can in principle
       degrade a pathological input): the original as-is, unrounded. Publishing a
       heavier but exact footprint is always better than publishing an invalid
       geometry.
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


# Cap on boxes per footprint in the index. Four is enough for the real cases
# that motivate the splitting: Russia straddling ±180°, Norway with Jan Mayen
# and Bouvet, the Netherlands with the Caribbean. Beyond that, each extra box
# barely refines the prefilter any more but grows the index for every footprint.
MAX_BBOXES = 4
# Beyond this number of parts, the greedy (quadratic) merge becomes expensive:
# we pre-aggregate the small parts onto the larger ones first.
_SEUIL_PRE_AGREGATION = 32


def _aire_bbox(boite: tuple[float, float, float, float]) -> float:
    return (boite[2] - boite[0]) * (boite[3] - boite[1])


def _union_bbox(a, b) -> tuple[float, float, float, float]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def part_bboxes(
    geometry: dict, max_boxes: int = MAX_BBOXES
) -> list[tuple[float, float, float, float]]:
    """Bboxes covering the footprint, one per group of nearby parts.

    The overall bbox of a multipolygon with far-apart parts discriminates nothing
    any more: Russia's (straddling the antimeridian) covers -180…180, Norway's
    reaches down to Bouvet at -54° of latitude. The viewer's prefilter would then
    download whole countries for clicks that have nothing to do with them — 8.3 MB
    of Russia for a click in London.

    Greedy merge: while there are too many boxes left, merge the two whose union
    wastes the least area. Nearby parts aggregate together; a distant island only
    merges as a last resort, so it keeps its own box as long as the cap allows.
    Every part stays covered by construction — boxes only ever grow.
    """
    forme = shape(geometry)
    parties = list(forme.geoms) if hasattr(forme, "geoms") else [forme]
    boites = [partie.bounds for partie in parties]

    if len(boites) > _SEUIL_PRE_AGREGATION:
        # National outlines have hundreds of islets: a quadratic merge over all
        # of them would be expensive for nothing. We keep the largest boxes as
        # seeds and aggregate each islet onto the one it grows the least.
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
    """Share of the area kept, between 0 and 1 (above 1 if it grew)."""
    aire = shape(original).area
    if aire == 0:
        return 1.0
    return shape(simplified).area / aire


def hausdorff(original: dict, simplified: dict) -> float:
    """Largest gap between the two outlines, in degrees."""
    return shape(original).hausdorff_distance(shape(simplified))
