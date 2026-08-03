from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import shape

from cartometa.build.geometry import DEFAULT_TOLERANCE, simplify_geometry
from cartometa.models import STATUS_TRACED, STATUSES
from cartometa.review.store import CountryPaths, load_metas

EXPORTABLE = (STATUS_TRACED,)

# Portée d'une emprise, telle que le site la donne à filtrer.
SCOPE_NATIONAL = "national"
SCOPE_REGIONAL = "regional"


def scope_de(pieces: list[dict]) -> str:
    """`national` si l'emprise EST le pays entier, `regional` sinon.

    Déduit du tracé, pas du `tier` Plonk It. Les deux existent et s'accordent
    à 96,8 % (mesuré sur les 1710 emprises publiées) mais ne disent pas la
    même chose : `tier` dit ce que Plonk It a classé, le tracé dit ce que
    l'emprise couvre réellement sur la carte. C'est cette seconde question que
    le filtre pose — et surtout, le tracé est *total* : toute emprise publiée
    en a un par construction, alors que `tier` vaut aussi `manual` pour une
    méta saisie à la main, valeur qui n'appartient ni au national ni au
    régional et laisserait ces métas hors des deux filtres.

    L'égalité stricte, et non `"country" in kinds` : une emprise mêlant
    `country` à un autre morceau est un pays rogné ou complété, donc
    précisément plus le pays entier. Aucune emprise publiée n'est dans ce cas
    aujourd'hui (les deux règles y sont équivalentes), mais seule l'égalité
    reste juste si cela change.

    Une liste vide retombe sur `regional` : aucune emprise publiée n'est dans
    ce cas non plus, et ce choix garantit qu'aucune méta ne peut disparaître
    de « All » — un défaut invisible serait pire qu'un classement discutable.
    """
    kinds = {piece.get("kind") for piece in pieces}
    return SCOPE_NATIONAL if kinds == {"country"} else SCOPE_REGIONAL


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
            # une erreur.
            continue
        metas = {m["id"]: m for m in load_metas(chemins)}
        if not metas:
            # Cas normal sur un clone frais, et non une anomalie : les 1710
            # emprises de `data/geo/` sont versionnées, leurs textes ne le
            # sont pas. Un contributeur tombe donc ici au premier
            # `cartometa-build` sans argument, dès le premier pays. Le
            # message doit lui donner sa sortie — publier son seul pays — et
            # pas seulement l'ordre de régénérer 45 pays qu'il ne possède pas.
            raise SystemExit(
                f"{pays} : {len(publiables)} emprise(s) versionnée(s), mais aucun "
                f"texte de méta.\n"
                f"Les textes Plonk It ne sont pas versionnés (data/metas/ est "
                f"gitignoré) : sur un clone frais c'est le cas de TOUS les pays, "
                f"et ce n'est pas une anomalie.\n"
                f"  - Pour prévisualiser le seul pays sur lequel tu travailles :\n"
                f"      uv run cartometa-build <CODE_PAYS>\n"
                f"  - Pour republier {pays} : cartometa-extract le régénère depuis "
                f"une page Plonk It sauvegardée à la main.\n"
                f"Les métas saisies à la main sont attendues dans "
                f"{chemins.manual_metas}."
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
                "scope": scope_de(feature["properties"].get("pieces", [])),
                "source_url": meta["source_url"],
                "image_source": meta.get("image"),
            }
        if entree_pays["geometries"]:
            jeu.countries[pays] = entree_pays
    # Trié par surface croissante : le viewer affiche du plus spécifique au
    # plus général sans avoir à trier lui-même.
    jeu.index.sort(key=lambda entree: entree[6])
    return jeu
