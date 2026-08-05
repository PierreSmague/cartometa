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

# Plonk It slugs whose name matches no Natural Earth name. Only add an entry
# here as a last resort: `--country XX` covers the one-off case without touching
# the code.
SLUG_OVERRIDES = {"usa": "US", "uk": "GB"}


def resolve_country(slug: str, cache_dir: Path) -> str:
    """Derive the ISO alpha-2 code from the Plonk It slug.

    Goes through the Natural Earth names, so that a new country requires no code
    change (spec §1).
    """
    if slug in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[slug]
    code = country_code_for_name(slug, cache_dir)
    if code is None:
        raise SystemExit(
            f"Cannot derive the country code from the slug \"{slug}\": no Natural "
            f"Earth name matches.\n"
            f"Re-run with the explicit code, for example: "
            f"cartometa-extract {slug} --country XX"
        )
    return code


def _find_page(input_dir: Path, slug: str) -> Path:
    """Find the saved .htm for a country.

    The comparison ignores case and separators: the Plonk It URL slug is written
    "south-africa" while the browser saves "South Africa — Plonk It.htm". Without
    that normalisation, every country whose name is several words long would be
    unfindable.

    Raises an explicit error if there is no candidate, or if several files match
    (e.g. a name collision from a second browser save, of the "Poland — Plonk It
    (1).htm" kind): better to fail loudly than to pick one silently.
    """
    def normalize(value: str) -> str:
        return " ".join(value.lower().replace("-", " ").replace("_", " ").split())

    target = normalize(slug)
    pages = sorted(input_dir.glob("*.htm*"))
    candidates = [p for p in pages if target in normalize(p.stem)]
    if not candidates:
        available = ", ".join(p.name for p in pages) or "none"
        raise FileNotFoundError(
            f"no saved page for '{slug}' in {input_dir}. "
            f"Pages present: {available}"
        )
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise ValueError(
            f"several saved pages match '{slug}' in {input_dir}: "
            f"{names} - delete the duplicates or rename to remove the ambiguity"
        )
    return candidates[0]


def _would_hit_network(url: str, cache: dict, retry_failed: bool) -> bool:
    """True if resolving `url` with these settings would really hit the network."""
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
    `retry_failed`: by default, a link already recorded as failed (`null` in the
    cache) is never retried — the historical behaviour. Passing `True` replays
    those failures only (already resolved links are never hit over the network
    again).

    `request_delay`: pause in seconds before each real network call, to stay polite
    towards Google when replaying several links. Has no effect on links already in
    the cache (neither successes nor failures that are not retried).
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
                anomalies.append(f"block {meta.id}: image not found ({meta.image})")
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
    parser = argparse.ArgumentParser(description="Extracts the metas from the saved pages")
    parser.add_argument("slug", nargs="?", default="poland", help="country, e.g. poland")
    parser.add_argument("--input", type=Path, default=Path("input"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument(
        "--country",
        help="ISO alpha-2 code, if the slug cannot be derived from a Natural Earth name.",
    )
    parser.add_argument("--no-resolve", action="store_true", help="do not resolve the Maps links")
    parser.add_argument(
        "--retry-failed-links",
        action="store_true",
        help=(
            "Replays the Maps links recorded as failed (null in the cache) - by "
            "default, a cached failure is never retried. Already resolved links are "
            "never hit over the network again."
        ),
    )
    parser.add_argument(
        "--link-delay",
        type=float,
        default=1.5,
        help="Pause in seconds before each real network call to resolve a link (polite towards Google).",
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

    print(f"{summary['country']}: {summary['total']} metas {summary['by_tier']}")
    print(f"  without image: {summary['without_image']}   without coordinates: {summary['without_latlon']}")
    for anomaly in summary["anomalies"]:
        print(f"  anomaly: {anomaly}")
    print(f"  written: {summary['output']}")
