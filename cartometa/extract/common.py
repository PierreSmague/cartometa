from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from cartometa.extract.maps_links import load_cache, resolve_maps_url, save_cache
from cartometa.models import MetaRecord

# Both extractors save their pages in the same input/ directory; the RMRG page
# titles all carry the site name ("Bangladesh GeoGuessr Guide - RMRG"), which is
# what lets each extractor find its own save for the same country.
RMRG_MARKER = "rmrg"


def _normalize(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def find_page(input_dir: Path, slug: str, rmrg: bool = False) -> Path:
    """Find the saved .htm for a country, for one source.

    The comparison ignores case and separators: the URL slug is written
    "south-africa" while the browser saves "South Africa — Plonk It.htm". Without
    that normalisation, every country whose name is several words long would be
    unfindable.

    `rmrg` selects the source: the RMRG save for Bangladesh ("Bangladesh
    GeoGuessr Guide - RMRG") also contains the slug, so without this filter the
    Plonk It lookup would become ambiguous the moment both saves exist.

    Raises an explicit error if there is no candidate, or if several files match
    (e.g. a name collision from a second browser save, of the "Poland — Plonk It
    (1).htm" kind): better to fail loudly than to pick one silently.
    """
    target = _normalize(slug)
    pages = sorted(input_dir.glob("*.htm*"))
    candidates = [
        p for p in pages
        if target in _normalize(p.stem)
        and (RMRG_MARKER in _normalize(p.stem).split()) == rmrg
    ]
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


def would_hit_network(url: str, cache: dict, retry_failed: bool) -> bool:
    """True if resolving `url` with these settings would really hit the network."""
    if url not in cache:
        return True
    return retry_failed and cache[url] is None


def project_relative_path(html_path: Path, input_dir: Path, raw: str) -> str | None:
    """Resolve a src relative to the saved page into a project-root-relative
    path with forward slashes, or None when the file does not exist on disk."""
    candidate = html_path.parent / raw
    if not candidate.exists():
        return None
    return str(candidate.relative_to(input_dir.parent)).replace("\\", "/")


def resolve_meta_links(
    metas: list[MetaRecord],
    cache_path: Path,
    resolve: bool,
    retry_failed: bool,
    request_delay: float,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Fill in `maps_latlon` for every meta that has a `maps_url`.

    `retry_failed`: by default, a link already recorded as failed (`null` in the
    cache) is never retried — the historical behaviour. Passing `True` replays
    those failures only (already resolved links are never hit over the network
    again).

    `request_delay`: pause in seconds before each real network call, to stay
    polite towards Google when replaying several links. Has no effect on links
    already in the cache (neither successes nor failures that are not retried).

    The cache is loaded and saved even when `resolve` is False, exactly like the
    historical inline loop.
    """
    cache = load_cache(cache_path)
    if resolve:
        for meta in metas:
            if not meta.maps_url:
                continue
            if request_delay > 0 and would_hit_network(meta.maps_url, cache, retry_failed):
                sleep(request_delay)
            meta.maps_latlon = resolve_maps_url(meta.maps_url, cache, retry_failed=retry_failed)
    save_cache(cache_path, cache)
