from __future__ import annotations
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable

LATLON_RE = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+)")
USER_AGENT = "cartometa/0.1 (usage personnel)"


def extract_latlon(url: str) -> tuple[float, float] | None:
    match = LATLON_RE.search(url)
    return (float(match.group(1)), float(match.group(2))) if match else None


def _default_opener(url: str) -> str:
    """Retourne l'URL finale après redirections, sans lire le corps."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.geturl()


def resolve_maps_url(
    url: str, cache: dict[str, Any], opener: Callable[[str], str] | None = None
) -> tuple[float, float] | None:
    if url in cache:
        value = cache[url]
        return tuple(value) if value else None
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
