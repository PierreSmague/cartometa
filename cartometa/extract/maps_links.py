from __future__ import annotations
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable

LATLON_RE = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+)")
# Deuxième forme observée sur des liens `goo.gl/maps` anciens (relecture
# finale, correction) : la redirection Google mène à un viewer panorama
# Street View de la forme `.../maps/@?api=1&map_action=pano&pano=...
# &viewpoint=LAT,LON&...`, sans coordonnées dans le chemin `/@LAT,LON`. Ce
# n'est pas un lien mort — juste un second format à reconnaître.
VIEWPOINT_RE = re.compile(r"[?&]viewpoint=(-?\d+\.\d+),(-?\d+\.\d+)")
USER_AGENT = "cartometa/0.1 (usage personnel)"


def extract_latlon(url: str) -> tuple[float, float] | None:
    match = LATLON_RE.search(url) or VIEWPOINT_RE.search(url)
    return (float(match.group(1)), float(match.group(2))) if match else None


def _default_opener(url: str) -> str:
    """Retourne l'URL finale après redirections, sans lire le corps."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.geturl()


def resolve_maps_url(
    url: str,
    cache: dict[str, Any],
    opener: Callable[[str], str] | None = None,
    retry_failed: bool = False,
) -> tuple[float, float] | None:
    """Résout un lien Maps court en (lat, lon), en s'appuyant sur un cache disque.

    Par défaut, un échec déjà mémorisé (``null`` en cache) n'est jamais retenté :
    c'est le comportement historique, silencieux vis-à-vis du réseau. Passer
    ``retry_failed=True`` lève cette règle pour les seules entrées en échec —
    un lien déjà résolu n'est, lui, jamais retapé sur le réseau.
    """
    if url in cache:
        value = cache[url]
        if value:
            return tuple(value)
        if not retry_failed:
            return None
        # value est None ici : échec mémorisé, mais on nous demande de rejouer.
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
