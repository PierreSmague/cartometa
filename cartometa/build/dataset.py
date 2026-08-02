from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import shape

from cartometa.build.geometry import DEFAULT_TOLERANCE, simplify_geometry
from cartometa.models import STATUS_TRACED, STATUSES
from cartometa.review.store import CountryPaths, load_metas

EXPORTABLE = (STATUS_TRACED,)


@dataclass
class Dataset:
    """Le jeu publiable, découpé.

    `index` est global et léger : il suffit à savoir, au clic, quels pays
    valent la peine d'être téléchargés. `countries` porte le détail, un
    fichier par pays.
    """

    index: list[list] = field(default_factory=list)
    countries: dict[str, dict] = field(default_factory=dict)
    legacy_statuses: int = 0


def discover_countries(data_dir: Path) -> list[str]:
    """Tous les pays ayant un fichier de géométries, par ordre alphabétique."""
    return sorted({p.stem.upper() for p in (data_dir / "geo").glob("*.geojson")})


def build_dataset(
    data_dir: Path, countries: list[str], tolerance: float = DEFAULT_TOLERANCE
) -> Dataset:
    """Lit les sources, simplifie, découpe par pays et construit l'index."""
    jeu = Dataset()
    for pays in countries:
        chemins = CountryPaths(data_dir, pays)
        if not chemins.geo.exists():
            continue
        geo = json.loads(chemins.geo.read_text("utf-8"))
        jeu.legacy_statuses += sum(
            1 for f in geo["features"] if f["properties"]["status"] not in STATUSES
        )
        publiables = [
            f for f in geo["features"]
            if f["properties"]["status"] in EXPORTABLE and f["geometry"]
        ]
        if not publiables:
            # Géojson vide ou tout en `rejeté` : rien à publier, ce n'est pas
            # une erreur. Un clone frais est exactement dans ce cas.
            continue
        metas = {m["id"]: m for m in load_metas(chemins)}
        if not metas:
            raise SystemExit(
                f"{pays} : géométries présentes mais aucune méta.\n"
                f"Les textes Plonk It ne sont pas versionnés — régénère-les avec "
                f"cartometa-extract, ou vérifie {chemins.manual_metas}."
            )
        entree_pays = {"metas": {}, "geometries": {}}
        for feature in publiables:
            identifiant = feature["properties"]["id"]
            meta = metas.get(identifiant)
            if meta is None:
                continue
            geometrie = simplify_geometry(feature["geometry"], tolerance)
            forme = shape(geometrie)
            min_lon, min_lat, max_lon, max_lat = forme.bounds
            jeu.index.append([
                identifiant, pays,
                round(min_lon, 4), round(min_lat, 4),
                round(max_lon, 4), round(max_lat, 4),
                round(forme.area, 6),
            ])
            entree_pays["geometries"][identifiant] = geometrie
            entree_pays["metas"][identifiant] = {
                "title": meta["title"],
                "description": meta["description"],
                "category": meta["category"],
                "source_url": meta["source_url"],
                "image_source": meta.get("image"),
            }
        if entree_pays["geometries"]:
            jeu.countries[pays] = entree_pays
    # Trié par surface croissante : le viewer affiche du plus spécifique au
    # plus général sans avoir à trier lui-même.
    jeu.index.sort(key=lambda entree: entree[6])
    return jeu
