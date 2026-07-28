from __future__ import annotations
import argparse
import json
from pathlib import Path

from cartometa.extract.categories import infer_category
from cartometa.extract.html_parser import parse_page
from cartometa.extract.maps_links import load_cache, resolve_maps_url, save_cache

COUNTRY_BY_SLUG = {"poland": ("PL", "https://www.plonkit.net/poland")}


def _find_page(input_dir: Path, slug: str) -> tuple[Path, Path]:
    """Retrouve le .htm sauvegardé et son dossier _files pour un pays."""
    for html_path in sorted(input_dir.glob("*.htm*")):
        if slug in html_path.stem.lower():
            assets = html_path.with_name(html_path.stem + "_files")
            return html_path, assets
    raise FileNotFoundError(f"aucune page sauvegardée pour '{slug}' dans {input_dir}")


def run_extract(
    input_dir: Path, data_dir: Path, country: str, base_url: str, resolve: bool = True
) -> dict:
    slug = base_url.rstrip("/").rsplit("/", 1)[-1]
    html_path, assets_dir = _find_page(input_dir, slug)
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
            meta.maps_latlon = resolve_maps_url(meta.maps_url, cache)

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
    parser.add_argument("--no-resolve", action="store_true", help="ne pas résoudre les liens Maps")
    args = parser.parse_args()

    country, base_url = COUNTRY_BY_SLUG[args.slug]
    summary = run_extract(args.input, args.data, country, base_url, resolve=not args.no_resolve)

    print(f"{summary['country']}: {summary['total']} métas {summary['by_tier']}")
    print(f"  sans image: {summary['without_image']}   sans coordonnées: {summary['without_latlon']}")
    for anomaly in summary["anomalies"]:
        print(f"  anomalie: {anomaly}")
    print(f"  écrit: {summary['output']}")
