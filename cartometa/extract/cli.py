from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
from typing import Callable

from cartometa.extract.categories import infer_category
from cartometa.extract.html_parser import parse_page
from cartometa.extract.maps_links import load_cache, resolve_maps_url, save_cache
from cartometa.geo.reference import country_code_for_name

BASE_URL = "https://www.plonkit.net"

# Slugs Plonk It dont le nom ne correspond à aucun nom Natural Earth.
# N'ajouter une entrée ici qu'en dernier recours : `--country XX` couvre
# le cas ponctuel sans toucher au code.
SLUG_OVERRIDES = {"usa": "US", "uk": "GB"}


def resolve_country(slug: str, cache_dir: Path) -> str:
    """Déduit le code ISO alpha-2 du slug Plonk It.

    Passe par les noms Natural Earth, pour qu'un nouveau pays ne demande
    aucune modification du code (spec §1).
    """
    if slug in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[slug]
    code = country_code_for_name(slug, cache_dir)
    if code is None:
        raise SystemExit(
            f"Impossible de déduire le code pays du slug « {slug} » : aucun nom "
            f"Natural Earth ne correspond.\n"
            f"Relance avec le code explicite, par exemple : "
            f"cartometa-extract {slug} --country XX"
        )
    return code


def _find_page(input_dir: Path, slug: str) -> Path:
    """Retrouve le .htm sauvegardé pour un pays.

    La comparaison ignore la casse et les séparateurs : le slug d'URL
    Plonk It s'écrit "south-africa" alors que le navigateur enregistre
    "South Africa — Plonk It.htm". Sans cette normalisation, tous les pays
    dont le nom fait plusieurs mots seraient introuvables.

    Lève une erreur explicite s'il n'y a aucun candidat ou si plusieurs
    fichiers correspondent (ex. collision de nom d'une seconde sauvegarde
    navigateur, du type "Poland — Plonk It (1).htm") : mieux vaut échouer
    bruyamment qu'en choisir un silencieusement.
    """
    def normalize(value: str) -> str:
        return " ".join(value.lower().replace("-", " ").replace("_", " ").split())

    target = normalize(slug)
    pages = sorted(input_dir.glob("*.htm*"))
    candidates = [p for p in pages if target in normalize(p.stem)]
    if not candidates:
        available = ", ".join(p.name for p in pages) or "aucune"
        raise FileNotFoundError(
            f"aucune page sauvegardée pour '{slug}' dans {input_dir}. "
            f"Pages présentes : {available}"
        )
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise ValueError(
            f"plusieurs pages sauvegardées correspondent à '{slug}' dans {input_dir} : "
            f"{names} — supprimez les doublons ou renommez pour lever l'ambiguïté"
        )
    return candidates[0]


def _would_hit_network(url: str, cache: dict, retry_failed: bool) -> bool:
    """Vrai si résoudre `url` avec ces réglages appellerait réellement le réseau."""
    if url not in cache:
        return True
    return retry_failed and cache[url] is None


def run_extract(
    input_dir: Path,
    data_dir: Path,
    country: str,
    base_url: str,
    resolve: bool = True,
    retry_failed: bool = False,
    request_delay: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """
    `retry_failed` : par défaut, un lien déjà mémorisé en échec (`null` en
    cache) n'est jamais retenté — comportement historique. Passer `True`
    rejoue uniquement ces échecs (les liens déjà résolus ne sont jamais
    retapés sur le réseau).

    `request_delay` : pause en secondes avant chaque appel réseau réel, pour
    rester poli envers Google lors d'un rejeu de plusieurs liens. N'a aucun
    effet sur les liens déjà en cache (ni succès, ni échec non retenté).
    """
    slug = base_url.rstrip("/").rsplit("/", 1)[-1]
    html_path = _find_page(input_dir, slug)
    metas, anomalies = parse_page(html_path.read_text("utf-8", errors="replace"), country, base_url)

    cache_path = data_dir / "cache" / "maps_links.json"
    cache = load_cache(cache_path)

    for meta in metas:
        meta.category = infer_category(meta.title, meta.description)
        if meta.image:
            candidate = html_path.parent / meta.image
            if candidate.exists():
                meta.image = str(candidate.relative_to(input_dir.parent)).replace("\\", "/")
            else:
                anomalies.append(f"bloc {meta.id}: image introuvable ({meta.image})")
                meta.image = None
        if resolve and meta.maps_url:
            if request_delay > 0 and _would_hit_network(meta.maps_url, cache, retry_failed):
                sleep(request_delay)
            meta.maps_latlon = resolve_maps_url(meta.maps_url, cache, retry_failed=retry_failed)

    save_cache(cache_path, cache)
    metas.sort(key=lambda m: m.id)

    out_path = data_dir / "metas" / f"{country}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([m.to_dict() for m in metas], indent=2, ensure_ascii=False), "utf-8"
    )

    by_tier: dict[str, int] = {}
    for meta in metas:
        by_tier[meta.tier] = by_tier.get(meta.tier, 0) + 1
    return {
        "country": country,
        "total": len(metas),
        "by_tier": by_tier,
        "without_image": sum(1 for m in metas if not m.image),
        "without_latlon": sum(1 for m in metas if m.maps_latlon is None),
        "anomalies": anomalies,
        "output": str(out_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrait les métas des pages sauvegardées")
    parser.add_argument("slug", nargs="?", default="poland", help="pays, ex. poland")
    parser.add_argument("--input", type=Path, default=Path("input"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument(
        "--country",
        help="Code ISO alpha-2, si le slug ne se déduit pas d'un nom Natural Earth.",
    )
    parser.add_argument("--no-resolve", action="store_true", help="ne pas résoudre les liens Maps")
    parser.add_argument(
        "--retry-failed-links",
        action="store_true",
        help=(
            "Rejoue les liens Maps mémorisés en échec (null en cache) — par défaut, "
            "un échec en cache n'est jamais retenté. Les liens déjà résolus ne sont "
            "jamais retapés sur le réseau."
        ),
    )
    parser.add_argument(
        "--link-delay",
        type=float,
        default=1.5,
        help="Pause en secondes avant chaque appel réseau réel de résolution de lien (poli envers Google).",
    )
    args = parser.parse_args()

    country = args.country.upper() if args.country else resolve_country(args.slug, args.data / "cache")
    base_url = f"{BASE_URL}/{args.slug}"
    summary = run_extract(
        args.input, args.data, country, base_url,
        resolve=not args.no_resolve,
        retry_failed=args.retry_failed_links,
        request_delay=args.link_delay,
    )

    print(f"{summary['country']}: {summary['total']} métas {summary['by_tier']}")
    print(f"  sans image: {summary['without_image']}   sans coordonnées: {summary['without_latlon']}")
    for anomaly in summary["anomalies"]:
        print(f"  anomalie: {anomaly}")
    print(f"  écrit: {summary['output']}")
