from __future__ import annotations
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable

LATLON_RE = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+)")
# Second form seen on older `goo.gl/maps` links (found during a final review,
# then fixed): the Google redirect leads to a Street View panorama viewer of the
# form `.../maps/@?api=1&map_action=pano&pano=...&viewpoint=LAT,LON&...`, with no
# coordinates in the `/@LAT,LON` path. That is not a dead link — just a second
# format to recognise.
VIEWPOINT_RE = re.compile(r"[?&]viewpoint=(-?\d+\.\d+),(-?\d+\.\d+)")
USER_AGENT = "cartometa/0.1 (usage personnel)"


def extract_latlon(url: str) -> tuple[float, float] | None:
    match = LATLON_RE.search(url) or VIEWPOINT_RE.search(url)
    return (float(match.group(1)), float(match.group(2))) if match else None


def _default_opener(url: str) -> str:
    """Return the final URL after redirects, without reading the body."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.geturl()


def resolve_maps_url(
    url: str,
    cache: dict[str, Any],
    opener: Callable[[str], str] | None = None,
    retry_failed: bool = False,
) -> tuple[float, float] | None:
    """Resolve a short Maps link into (lat, lon), backed by an on-disk cache.

    By default, an already-recorded failure (``null`` in the cache) is never
    retried: that is the historical behaviour, silent as far as the network is
    concerned. Passing ``retry_failed=True`` lifts that rule for failed entries
    only — an already resolved link is never hit over the network again.
    """
    if url in cache:
        value = cache[url]
        if value:
            return tuple(value)
        if not retry_failed:
            return None
        # value is None here: a recorded failure, but we are asked to replay it.
    try:
        final_url = (opener or _default_opener)(url)
        latlon = extract_latlon(final_url)
    except OSError:
        latlon = None
    cache[url] = list(latlon) if latlon else None
    return latlon


def load_cache(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def save_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), "utf-8")
