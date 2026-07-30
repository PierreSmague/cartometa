from __future__ import annotations

from pathlib import Path
from typing import Any

from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from cartometa.geo.admin1 import region_geometry
from cartometa.geo.reference import country_geometry

MIN_RING_POINTS = 3
# Un contour tracé à la souris compte quelques dizaines de sommets. Ce
# plafond n'est pas une limite ergonomique mais un garde-fou : il empêche
# qu'un client incorrect fasse tourner shapely sur une liste sans fin.
MAX_RING_POINTS = 2000


class PieceError(ValueError):
    """Morceau de zone illisible, invalide, ou hors des bornes terrestres."""


def _check_lonlat(lon: Any, lat: Any) -> tuple[float, float]:
    try:
        x, y = float(lon), float(lat)
    except (TypeError, ValueError):
        raise PieceError(f"coordonnée non numérique : ({lon!r}, {lat!r})") from None
    if not (-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0):
        raise PieceError(f"coordonnée hors des bornes WGS84 : ({x}, {y})")
    return x, y


def _rectangle(piece: dict) -> BaseGeometry:
    bounds = piece.get("bounds")
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise PieceError("un rectangle demande bounds = [ouest, sud, est, nord]")
    west, south = _check_lonlat(bounds[0], bounds[1])
    east, north = _check_lonlat(bounds[2], bounds[3])
    # Les deux clics arrivent dans l'ordre où l'humain les a posés, pas dans
    # l'ordre géographique : on normalise plutôt que de refuser.
    west, east = min(west, east), max(west, east)
    south, north = min(south, north), max(south, north)
    if west == east or south == north:
        raise PieceError("rectangle de surface nulle")
    return box(west, south, east, north)


def _contour(piece: dict) -> BaseGeometry:
    ring = piece.get("ring")
    if not isinstance(ring, (list, tuple)):
        raise PieceError("un contour demande ring = [[lon, lat], …]")
    if not (MIN_RING_POINTS <= len(ring) <= MAX_RING_POINTS):
        raise PieceError(
            f"un contour demande entre {MIN_RING_POINTS} et {MAX_RING_POINTS} "
            f"sommets, reçu {len(ring)}"
        )
    points = []
    for vertex in ring:
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 2:
            raise PieceError(f"sommet illisible : {vertex!r}")
        points.append(_check_lonlat(vertex[0], vertex[1]))

    geom = Polygon(points)
    if not geom.is_valid:
        # Un contour tracé à la souris s'auto-intersecte facilement.
        # `buffer(0)` le répare sans trahir l'intention — même traitement
        # que les contours Natural Earth abîmés (cf. country_geometry).
        geom = geom.buffer(0)
    if geom.is_empty or geom.area <= 0.0:
        raise PieceError("contour de surface nulle")
    return geom


def _region(piece: dict, country: str, cache_dir: Path) -> BaseGeometry:
    code = piece.get("code")
    if not isinstance(code, str) or not code:
        raise PieceError("un morceau admin1 demande le code de la région")
    try:
        return region_geometry(country, code, cache_dir)
    except KeyError as exc:
        raise PieceError(str(exc)) from None


def _country(country: str, cache_dir: Path) -> BaseGeometry:
    try:
        return country_geometry(country, cache_dir)
    except KeyError as exc:
        raise PieceError(str(exc)) from None


def resolve_pieces(pieces: list[dict], country: str, cache_dir: Path) -> BaseGeometry:
    """Union des morceaux d'une zone, résolus côté serveur.

    Le client n'envoie que des descripteurs : `{"kind": "country"}` ou
    `{"kind": "admin1", "code": …}` sont résolus ici depuis Natural Earth,
    jamais reçus sous forme de coordonnées. Une silhouette publiée est donc
    toujours celle du référentiel, quoi qu'ait affiché le navigateur.
    """
    if not isinstance(pieces, (list, tuple)) or not pieces:
        raise PieceError("aucun morceau : il n'y a rien à enregistrer")

    geometries = []
    for piece in pieces:
        if not isinstance(piece, dict):
            raise PieceError(f"morceau illisible : {piece!r}")
        kind = piece.get("kind")
        if kind == "country":
            geometries.append(_country(country, cache_dir))
        elif kind == "admin1":
            geometries.append(_region(piece, country, cache_dir))
        elif kind == "rect":
            geometries.append(_rectangle(piece))
        elif kind == "polygon":
            geometries.append(_contour(piece))
        else:
            raise PieceError(f"type de morceau inconnu : {kind!r}")

    union = unary_union(geometries)
    if union.is_empty or not union.is_valid or union.area <= 0.0:
        raise PieceError("l'union des morceaux ne donne aucune surface valide")
    return union
