from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from shapely.geometry import shape

from cartometa.build.geometry import DEFAULT_TOLERANCE, part_bboxes, simplify_geometry
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
    # Emprises tracées dont le texte de méta a disparu : (pays, id). Comptées
    # pour être nommées par le CLI — une donnée qui s'évapore en silence est
    # pire qu'un build qui râle.
    orphans: list[tuple[str, str]] = field(default_factory=list)


def empreinte_geometrie(geometrie: dict) -> str:
    """Empreinte de contenu d'une géométrie, clé de sa publication.

    Beaucoup de métas partagent la même emprise — 19 fois le contour national
    dans le seul fichier russe, 25,9 Mo de doublons byte-identiques sur les
    34,2 Mo publiés (mesuré). Publier chaque géométrie une seule fois, sous
    une clé qui ne dépend que de son contenu, supprime le doublon sans que le
    front ait rien à recalculer. Douze hexdigits suffisent largement : le
    risque de collision reste négligeable bien au-delà du million d'emprises.
    """
    octets = json.dumps(geometrie, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(octets).hexdigest()[:12]


def discover_countries(data_dir: Path) -> list[str]:
    """Tous les pays ayant un fichier de géométries, par ordre alphabétique."""
    return sorted({p.stem.upper() for p in (data_dir / "geo").glob("*.geojson")})


def build_dataset(
    data_dir: Path,
    countries: list[str],
    tolerance: float = DEFAULT_TOLERANCE,
    outline_de: Callable[[str], dict | None] | None = None,
) -> Dataset:
    """Lit les sources, simplifie, découpe par pays et construit l'index.

    `outline_de` fournit, pour un code pays, la silhouette du pays en GeoJSON
    — ou `None` quand elle est indisponible. Absent, aucun fichier pays ne
    porte de clé `outline`.
    """
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
                jeu.orphans.append((pays, identifiant))
                continue
            geometrie = simplify_geometry(feature["geometry"], tolerance)
            forme = shape(geometrie)
            # Une ligne d'index par groupe de parties, pas par emprise : la
            # bbox globale d'un multipolygone éclaté (Russie sur ±180°,
            # Norvège jusqu'à Bouvet) couvre la planète et ne préfiltre plus
            # rien. Même id et même surface sur chaque ligne — le viewer
            # déduplique les ids, le tri par surface reste stable.
            surface = round(forme.area, 6)
            for min_lon, min_lat, max_lon, max_lat in part_bboxes(geometrie):
                jeu.index.append([
                    identifiant, pays,
                    round(min_lon, 4), round(min_lat, 4),
                    round(max_lon, 4), round(max_lat, 4),
                    surface,
                ])
            empreinte = empreinte_geometrie(geometrie)
            entree_pays["geometries"][empreinte] = geometrie
            entree_pays["metas"][identifiant] = {
                "geom": empreinte,
                "title": meta["title"],
                "description": meta["description"],
                "category": meta["category"],
                "scope": scope_de(feature["properties"].get("pieces", [])),
                "source_url": meta["source_url"],
                "image_source": meta.get("image"),
            }
        if entree_pays["geometries"] and outline_de is not None:
            # Silhouette du pays, fond de la mini-carte des cartes Anki.
            # Injectée plutôt qu'importée : le dataset Natural Earth vient du
            # réseau, et ni cette fonction ni ses tests ne doivent y toucher.
            contour = outline_de(pays)
            if contour is not None:
                entree_pays["outline"] = simplify_geometry(contour, tolerance)
        if entree_pays["geometries"]:
            jeu.countries[pays] = entree_pays
    # Une orpheline Plonk It est un décalage de régénération, rattrapable en
    # relançant cartometa-extract : on la compte et le CLI la nomme. Une
    # orpheline `man-*` est autre chose : data/manual/ est versionné justement
    # parce que ces saisies sont irremplaçables, donc son texte n'existe plus
    # nulle part. Publier sans elle serait entériner la perte en silence.
    perdues = [(pays, i) for pays, i in jeu.orphans if i.startswith("man-")]
    if perdues:
        details = "\n".join(f"  - {pays} : {i}" for pays, i in perdues)
        raise SystemExit(
            f"{len(perdues)} emprise(s) manuelle(s) sans texte de méta :\n{details}\n"
            f"Le texte d'une méta manuelle vit dans data/manual/<CC>/metas.json "
            f"et est versionné : s'il manque, il a été supprimé ou renommé. "
            f"Restaure-le depuis git, ou retire l'emprise du geojson si la "
            f"suppression était voulue."
        )
    # Trié par surface croissante : le viewer affiche du plus spécifique au
    # plus général sans avoir à trier lui-même.
    jeu.index.sort(key=lambda entree: entree[6])
    return jeu
