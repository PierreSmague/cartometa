from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cartometa.atomic_write import write_json_atomic
from cartometa.models import (
    ORIGIN_TAGGED,
    STATUS_PROPOSED,
    STATUSES,
    TIER_MANUAL,
    GeoRecord,
)
from cartometa.review.store import CountryPaths, load_geo, read_json_list, save_geo
from cartometa.tagged.countries import CountryIndex
from cartometa.tagged.geometry import corridor_geometry, geometry_to_pieces, zone_geometry

# Pre-simplification of the generated footprints, in degrees: ~50 m keeps a
# 500 m ribbon faithful, ~500 m is plenty for hulls inflated by 10 km.
SIMPLIFY_DEG = {"route": 0.0005, "zone": 0.005}
DEFAULT_LINK_KM = {"route": 5.0, "zone": 40.0}
REVIEW_PORT = 8799


class TaggedFileError(ValueError):
    """Import refused: unreadable input, active review session, or id collision."""


@dataclass
class TagReport:
    tag: str
    country: str
    points: int
    pieces: int
    action: str


@dataclass
class ImportReport:
    source: str
    mode: str
    untagged: int = 0
    unplaced: int = 0
    rows: list[TagReport] = field(default_factory=list)


def proposal_id(name: str, tag: str, country: str) -> str:
    """Deterministic id: re-runs regenerate the same records instead of duplicating.

    The `tag-` prefix keeps it apart from `man-` (4 hex) and from Plonk It ids
    (4 chars, no prefix); 6 hex keep the collision odds negligible at the scale
    of a few dozen metas per file — and a collision fails frankly (cf. caller).
    """
    digest = hashlib.sha1(f"{name}|{tag}|{country}".encode("utf-8")).hexdigest()
    return f"tag-{digest[:6]}"


def parse_tagged_file(path: Path) -> tuple[str, list[tuple[float, float, list[str]]]]:
    """(logical name, [(lat, lng, tags), ...]) — tags may be empty, caller counts."""
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaggedFileError(f"{path}: unreadable JSON ({exc})") from None
    coords = data.get("customCoordinates") if isinstance(data, dict) else None
    if not isinstance(coords, list) or not coords:
        raise TaggedFileError(f"{path}: no customCoordinates list")
    name = data.get("name") or path.stem
    points = []
    for entry in coords:
        try:
            lat, lng = float(entry["lat"]), float(entry["lng"])
        except (KeyError, TypeError, ValueError):
            raise TaggedFileError(f"{path}: point without usable lat/lng: {entry!r}") from None
        tags = entry.get("extra", {}).get("tags") or []
        points.append((lat, lng, [str(t) for t in tags]))
    return name, points


def _review_running(port: int = REVIEW_PORT) -> bool:
    # The review server rewrites data/geo as decisions land: importing under it
    # would interleave two writers on the same files. Detection is best-effort
    # (a session on a custom --port slips through) but catches the normal case.
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _build_geometry(points, mode, buffer_m, link_km, hull_buffer_km):
    if mode == "route":
        return corridor_geometry(points, buffer_m=buffer_m, link_km=link_km)
    return zone_geometry(points, hull_buffer_km=hull_buffer_km, link_km=link_km)


def import_tagged(
    data_dir: Path,
    file: Path,
    *,
    mode: str,
    category: str,
    buffer_m: float = 250.0,
    link_km: float | None = None,
    hull_buffer_km: float = 10.0,
    dry_run: bool = False,
) -> ImportReport:
    if mode not in SIMPLIFY_DEG:
        raise TaggedFileError(f"unknown mode: {mode!r} (expected route or zone)")
    if not dry_run and _review_running():
        raise TaggedFileError(
            "a cartometa-review session seems active (port 8799 answers): "
            "both write data/geo — stop it before importing."
        )
    link = DEFAULT_LINK_KM[mode] if link_km is None else link_km
    name, raw_points = parse_tagged_file(file)
    report = ImportReport(source=name, mode=mode)

    index = CountryIndex(data_dir / "cache")
    groups: dict[tuple[str, str], list[tuple[float, float]]] = {}
    placement: dict[tuple[float, float], str | None] = {}
    for lat, lng, tags in raw_points:
        if not tags:
            report.untagged += 1
            continue
        key = (lat, lng)
        if key not in placement:
            placement[key] = index.country_of(lat, lng)
        country = placement[key]
        if country is None:
            report.unplaced += 1
            continue
        for tag in tags:
            groups.setdefault((tag, country), []).append((lat, lng))

    by_country: dict[str, list[tuple[str, str, list, list[dict]]]] = {}
    seen_ids: dict[str, tuple[str, str]] = {}
    for (tag, country), points in sorted(groups.items()):
        pid = proposal_id(name, tag, country)
        if pid in seen_ids:
            raise TaggedFileError(
                f"id collision: {seen_ids[pid]} and {(tag, country)} both give {pid}"
            )
        seen_ids[pid] = (tag, country)
        geom = _build_geometry(points, mode, buffer_m, link, hull_buffer_km)
        pieces = geometry_to_pieces(geom, SIMPLIFY_DEG[mode])
        by_country.setdefault(country, []).append((pid, tag, points, pieces))

    now = datetime.now(timezone.utc).isoformat()
    for country, proposals in sorted(by_country.items()):
        paths = CountryPaths(data_dir, country)
        records = load_geo(paths)
        metas = {m["id"]: m for m in read_json_list(paths.tagged_metas)}
        touched = False
        for pid, tag, points, pieces in proposals:
            existing = records.get(pid)
            if existing is not None and existing.status in STATUSES:
                report.rows.append(TagReport(tag, country, len(points), len(pieces),
                                             "sautée (décidée)"))
                continue
            meta = {
                "id": pid, "country": country, "tier": TIER_MANUAL,
                "title": tag, "description": tag, "category": category,
                "source_url": "",
                # Kept across re-runs: two identical runs must be byte-identical.
                "extracted_at": metas.get(pid, {}).get("extracted_at", now),
                "description_origin": "imported", "origin": ORIGIN_TAGGED,
                "image": None, "maps_url": None, "maps_latlon": None,
                "source_file": name, "source_tag": tag,
            }
            record = GeoRecord(id=pid, geometry=None, pieces=pieces,
                               status=STATUS_PROPOSED)
            if existing is None:
                action = "écrite"
            elif metas.get(pid) == meta and _same_pieces(existing.pieces, pieces):
                action = "inchangée"
            else:
                action = "réécrite"
            report.rows.append(TagReport(tag, country, len(points), len(pieces), action))
            if action != "inchangée":
                touched = True
            metas[pid] = meta
            records[pid] = record
        if not dry_run and touched:
            paths.tagged_metas.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(paths.tagged_metas,
                              [metas[k] for k in sorted(metas)])
            save_geo(paths, records)
    return report


def _same_pieces(stored: list[dict], generated: list[dict]) -> bool:
    """Stored pieces went through save_geo's 5-decimal rounding: compare in
    that space, not raw floats against rounded ones."""
    def _round(value):
        if isinstance(value, float):
            return round(value, 5)
        if isinstance(value, list):
            return [_round(v) for v in value]
        if isinstance(value, dict):
            return {k: _round(v) for k, v in value.items()}
        return value

    return _round(stored) == _round(generated)
