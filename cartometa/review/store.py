from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import Polygon, shape

from cartometa.atomic_write import write_json_atomic
from cartometa.models import ORIGIN_PLONKIT, STATUSES, GeoRecord


class UnknownMetaError(ValueError):
    """Levée quand un `id` ne correspond à aucune méta connue du pays."""


@dataclass(frozen=True)
class CountryPaths:
    """Les six chemins d'un pays, en un seul endroit.

    Deux sources de métas cohabitent : l'import Plonk It, gitignoré parce que
    régénérable, et la saisie manuelle, versionnée parce qu'irremplaçable.
    Les réunir ici évite que chaque appelant réinvente la convention.
    """

    data: Path
    country: str

    @property
    def imported_metas(self) -> Path:
        return self.data / "metas" / f"{self.country}.json"

    @property
    def manual_dir(self) -> Path:
        return self.data / "manual" / self.country

    @property
    def manual_metas(self) -> Path:
        return self.manual_dir / "metas.json"

    @property
    def manual_images(self) -> Path:
        return self.manual_dir / "images"

    @property
    def geo(self) -> Path:
        return self.data / "geo" / f"{self.country}.geojson"

    @property
    def cache(self) -> Path:
        return self.data / "cache"


def read_json_list(path: Path) -> list[dict]:
    """Liste JSON, ou liste vide si le fichier n'existe pas.

    Une source absente n'est pas une erreur : un pays peut n'avoir que des
    métas importées, ou que des métas manuelles.
    """
    if not path.exists():
        return []
    return json.loads(path.read_text("utf-8"))


def load_metas(paths: CountryPaths) -> list[dict]:
    """Métas importées puis manuelles, dans cet ordre."""
    return read_json_list(paths.imported_metas) + read_json_list(paths.manual_metas)


def load_geo(paths: CountryPaths) -> dict[str, GeoRecord]:
    if not paths.geo.exists():
        return {}
    data = json.loads(paths.geo.read_text("utf-8"))
    records = [GeoRecord.from_feature(f) for f in data.get("features", [])]
    return {record.id: record for record in records}


def _arrondi_coords(valeur):
    """Arrondit récursivement tout flottant à 5 décimales (~1 m au sol).

    Appliqué à la géométrie et aux `pieces`, qui ne portent que des
    coordonnées : les quinze décimales d'un float64 sérialisé sont du bruit
    de calcul, pas de l'information — et du poids versionné à chaque trace.
    """
    if isinstance(valeur, float):
        return round(valeur, 5)
    if isinstance(valeur, list):
        return [_arrondi_coords(v) for v in valeur]
    if isinstance(valeur, dict):
        return {k: _arrondi_coords(v) for k, v in valeur.items()}
    return valeur


def _geometrie_arrondie(geometry: dict | None) -> dict | None:
    """La géométrie arrondie, ou telle quelle si l'arrondi la dégénère.

    Recoller deux sommets distants de moins de 1e-5° peut faire passer un
    anneau deux fois par le même point : 8 emprises sur 3617 ont dégénéré
    ainsi à la première migration. Même philosophie que `simplify_geometry` :
    stocker plus lourd mais exact vaut toujours mieux que stocker invalide.
    """
    if geometry is None:
        return None
    arrondie = _arrondi_coords(geometry)
    try:
        forme = shape(arrondie)
        if forme.is_valid and not forme.is_empty:
            return arrondie
    except Exception:
        pass
    return geometry


def _piece_arrondie(piece: dict) -> dict:
    """Comme la géométrie : un anneau n'est arrondi que sans régression.

    Les anneaux servent à rouvrir une méta (`resolve_pieces` les reconstruit
    en polygones) : un anneau valide ne doit pas devenir invalide au passage.
    Un anneau déjà invalide — quatre tracés main le sont — est arrondi tel
    quel : il n'y a rien à préserver.
    """
    arrondie = _arrondi_coords(piece)
    anneau = piece.get("ring")
    if piece.get("kind") == "polygon" and anneau and len(anneau) >= 3:
        try:
            if Polygon(anneau).is_valid and not Polygon(arrondie["ring"]).is_valid:
                arrondie["ring"] = anneau
        except Exception:
            arrondie["ring"] = anneau
    return arrondie


def _feature_arrondie(feature: dict) -> dict:
    feature["geometry"] = _geometrie_arrondie(feature["geometry"])
    feature["properties"]["pieces"] = [
        _piece_arrondie(p) for p in feature["properties"]["pieces"]
    ]
    return feature


def save_geo(paths: CountryPaths, records: dict[str, GeoRecord]) -> None:
    # Compact, pas indenté : l'indentation coûtait un facteur 4 mesuré
    # (RU.geojson : 90 Mo indenté, 25 Mo compact), sur des fichiers versionnés
    # réécrits en entier à chaque décision.
    write_json_atomic(paths.geo, {
        "type": "FeatureCollection",
        "features": [
            _feature_arrondie(records[key].to_feature()) for key in sorted(records)
        ],
    }, indent=None)


def _image_url(meta: dict) -> str | None:
    # Les deux sources stockent un chemin relatif à la racine du projet, que
    # le serveur sert tel quel.
    return "/" + meta["image"] if meta.get("image") else None


def build_queue(paths: CountryPaths, include_all: bool = False) -> dict:
    """File de revue du pays.

    Par défaut, les métas déjà tracées ou rejetées en sont exclues.
    `include_all` les rouvre avec leurs morceaux, pour repasser sur un pays
    quand une nouvelle source donne mieux.
    """
    metas = load_metas(paths)
    geo = load_geo(paths)
    items = []
    queued_ids = set()
    for meta in metas:
        record = geo.get(meta["id"])
        if record is not None and not include_all:
            continue
        queued_ids.add(meta["id"])
        items.append({
            "id": meta["id"],
            "title": meta["title"],
            "description": meta["description"],
            "category": meta["category"],
            "tier": meta["tier"],
            "origin": meta.get("origin", ORIGIN_PLONKIT),
            "image": _image_url(meta),
            "latlon": meta.get("maps_latlon"),
            "source_url": meta.get("source_url", ""),
            "status": record.status if record is not None else None,
            "pieces": record.pieces if record is not None else [],
        })
    # `done` compte les métas déjà décidées mais ABSENTES de la file rendue,
    # pas simplement `len(geo)` : par défaut les deux coïncident (une méta
    # décidée est toujours exclue de la file), mais sous `include_all` tout
    # est rouvert et remis dans la file, donc `done` retombe à 0. C'est ce
    # qui permet à l'appelant JS de garder la même formule
    # `done + index courant` dans les deux modes, sans code spécifique.
    done = sum(1 for meta_id in geo if meta_id not in queued_ids)
    return {
        "country": paths.country,
        "total": len(metas),
        "done": done,
        "items": items,
    }


def set_decision(
    paths: CountryPaths,
    meta_id: str,
    status: str,
    geometry: dict | None,
    pieces: list[dict],
) -> None:
    if status not in STATUSES:
        raise ValueError(f"statut inconnu : {status!r} (attendu {' ou '.join(STATUSES)})")
    if meta_id not in {meta["id"] for meta in load_metas(paths)}:
        raise UnknownMetaError(f"méta inconnue : {meta_id!r}")
    records = load_geo(paths)
    records[meta_id] = GeoRecord(
        id=meta_id, geometry=geometry, pieces=list(pieces), status=status
    )
    save_geo(paths, records)


def clear_decision(paths: CountryPaths, meta_id: str) -> None:
    """Remet une méta à l'état « à faire » en retirant sa décision."""
    records = load_geo(paths)
    if meta_id not in records:
        raise UnknownMetaError(f"aucune décision à annuler pour {meta_id!r}")
    del records[meta_id]
    save_geo(paths, records)
