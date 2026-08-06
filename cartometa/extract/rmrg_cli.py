from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Callable

from cartometa.extract.cli import resolve_country
from cartometa.extract.common import find_page, project_relative_path, resolve_meta_links
from cartometa.extract.rmrg import parse_rmrg_page, prepare_overlay

BASE_URL = "https://rmrg.me"


def run_extract_rmrg(
    input_dir: Path,
    data_dir: Path,
    country: str,
    slugs: list[str],
    resolve: bool = True,
    retry_failed: bool = False,
    request_delay: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """The RMRG counterpart of `run_extract`, writing `<CC>-rmrg.json`.

    A separate file, not a merge into `<CC>.json`: each extractor owns its
    output, so re-running either source can never erase the other's metas.

    Several slugs merge into the one country file — RMRG splits Indonesia into
    a general guide plus one guide per island. Each meta keeps the source_url
    of its own page; a block id published by two pages is refused loudly, it
    would silently collapse into one queue entry and one footprint.
    """
    metas = []
    anomalies: list[str] = []
    seen: dict[str, str] = {}
    for slug in slugs:
        base_url = f"{BASE_URL}/{slug}/"
        html_path = find_page(input_dir, slug, rmrg=True)
        page_metas, page_anomalies = parse_rmrg_page(
            html_path.read_text("utf-8", errors="replace"), country, base_url
        )
        anomalies.extend(page_anomalies)

        for meta in page_metas:
            if meta.id in seen:
                raise SystemExit(
                    f"id '{meta.id}' published by both '{seen[meta.id]}' and "
                    f"'{slug}': the pages of a group must not share block ids."
                )
            seen[meta.id] = slug
            if meta.image:
                resolved = project_relative_path(html_path, input_dir, meta.image)
                if resolved is None:
                    anomalies.append(f"block {meta.id}: image not found ({meta.image})")
                meta.image = resolved
            if meta.overlay:
                candidate = html_path.parent / meta.overlay
                readable = prepare_overlay(candidate) if candidate.exists() else None
                if readable is None:
                    anomalies.append(f"block {meta.id}: unreadable overlay ({meta.overlay})")
                    meta.overlay = None
                else:
                    meta.overlay = str(readable.relative_to(input_dir.parent)).replace("\\", "/")
        metas.extend(page_metas)

    resolve_meta_links(
        metas, data_dir / "cache" / "maps_links.json",
        resolve=resolve, retry_failed=retry_failed,
        request_delay=request_delay, sleep=sleep,
    )
    metas.sort(key=lambda m: m.id)

    out_path = data_dir / "metas" / f"{country}-rmrg.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([m.to_dict() for m in metas], indent=2, ensure_ascii=False), "utf-8"
    )

    by_category: dict[str, int] = {}
    for meta in metas:
        by_category[meta.category] = by_category.get(meta.category, 0) + 1
    return {
        "country": country,
        "total": len(metas),
        "pages": len(slugs),
        "by_category": by_category,
        "without_image": sum(1 for m in metas if not m.image),
        "without_latlon": sum(1 for m in metas if m.maps_latlon is None),
        "without_overlay": sum(1 for m in metas if not m.overlay),
        "anomalies": anomalies,
        "output": str(out_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extracts the metas from saved RMRG guides")
    parser.add_argument(
        "slugs", nargs="+",
        help=(
            "one or more page slugs merged under one country, e.g. 'bangladesh', "
            "or 'indonesia java kalimantan nusa-islands sulawesi-maluku sumatra'"
        ),
    )
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

    # The country comes from the FIRST slug: for a multi-page group, lead with
    # the general guide ("indonesia java ..."), or pass --country explicitly.
    country = args.country.upper() if args.country else resolve_country(args.slugs[0], args.data / "cache")
    summary = run_extract_rmrg(
        args.input, args.data, country, args.slugs,
        resolve=not args.no_resolve,
        retry_failed=args.retry_failed_links,
        request_delay=args.link_delay,
    )

    print(
        f"{summary['country']}: {summary['total']} metas "
        f"({summary['pages']} page(s)) {summary['by_category']}"
    )
    print(
        f"  without image: {summary['without_image']}   "
        f"without coordinates: {summary['without_latlon']}   "
        f"without overlay: {summary['without_overlay']}"
    )
    for anomaly in summary["anomalies"]:
        print(f"  anomaly: {anomaly}")
    print(f"  written: {summary['output']}")
