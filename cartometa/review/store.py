from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import Polygon, shape

from cartometa.atomic_write import write_json_atomic
from cartometa.models import ORIGIN_PLONKIT, STATUSES, GeoRecord


class UnknownMetaError(ValueError):
    """Raised when an `id` matches no meta known for the country."""


@dataclass(frozen=True)
class CountryPaths:
    """A country's six paths, in one single place.

    Two sources of metas coexist: the Plonk It import, gitignored because it is
    regenerable, and manual entry, versioned because it is irreplaceable. Gathering
    them here saves every caller from reinventing the convention.
    """

    data: Path
    country: str

    @property
    def imported_metas(self) -> Path:
        return self.data / "metas" / f"{self.country}.json"

    @property
    def manual_dir(self) -> Path:
        return self.data / "manual" / self.country

    @property
    def manual_metas(self) -> Path:
        return self.manual_dir / "metas.json"

    @property
    def manual_images(self) -> Path:
        return self.manual_dir / "images"

    @property
    def geo(self) -> Path:
        return self.data / "geo" / f"{self.country}.geojson"

    @property
    def cache(self) -> Path:
        return self.data / "cache"


def read_json_list(path: Path) -> list[dict]:
    """A JSON list, or an empty list if the file does not exist.

    A missing source is not an error: a country may have only imported metas, or
    only manual ones.
    """
    if not path.exists():
        return []
    return json.loads(path.read_text("utf-8"))


def load_metas(paths: CountryPaths) -> list[dict]:
    """Imported metas then manual ones, in that order."""
    return read_json_list(paths.imported_metas) + read_json_list(paths.manual_metas)


def load_geo(paths: CountryPaths) -> dict[str, GeoRecord]:
    if not paths.geo.exists():
        return {}
    data = json.loads(paths.geo.read_text("utf-8"))
    records = [GeoRecord.from_feature(f) for f in data.get("features", [])]
    return {record.id: record for record in records}


def _arrondi_coords(valeur):
    """Recursively round every float to 5 decimals (~1 m on the ground).

    Applied to the geometry and to the `pieces`, which carry nothing but
    coordinates: the fifteen decimals of a serialised float64 are computation noise,
    not information — and versioned weight on every drawing.
    """
    if isinstance(valeur, float):
        return round(valeur, 5)
    if isinstance(valeur, list):
        return [_arrondi_coords(v) for v in valeur]
    if isinstance(valeur, dict):
        return {k: _arrondi_coords(v) for k, v in valeur.items()}
    return valeur


def _geometrie_arrondie(geometry: dict | None) -> dict | None:
    """The rounded geometry, or the geometry as-is if rounding degenerates it.

    Gluing together two vertices less than 1e-5° apart can make a ring pass twice
    through the same point: 8 footprints out of 3617 degenerated that way during the
    first migration. Same philosophy as `simplify_geometry`: storing heavier but
    exact is always better than storing invalid.
    """
    if geometry is None:
        return None
    arrondie = _arrondi_coords(geometry)
    try:
        forme = shape(arrondie)
        if forme.is_valid and not forme.is_empty:
            return arrondie
    except Exception:
        pass
    return geometry


def _piece_arrondie(piece: dict) -> dict:
    """Like the geometry: a ring is only rounded when that causes no regression.

    Rings are what makes reopening a meta possible (`resolve_pieces` rebuilds them
    into polygons): a valid ring must not become invalid along the way. A ring that
    is already invalid — four hand drawings are — is rounded as-is: there is nothing
    to preserve.
    """
    arrondie = _arrondi_coords(piece)
    anneau = piece.get("ring")
    if piece.get("kind") == "polygon" and anneau and len(anneau) >= 3:
        try:
            if Polygon(anneau).is_valid and not Polygon(arrondie["ring"]).is_valid:
                arrondie["ring"] = anneau
        except Exception:
            arrondie["ring"] = anneau
    return arrondie


def _feature_arrondie(feature: dict) -> dict:
    feature["geometry"] = _geometrie_arrondie(feature["geometry"])
    feature["properties"]["pieces"] = [
        _piece_arrondie(p) for p in feature["properties"]["pieces"]
    ]
    return feature


def save_geo(paths: CountryPaths, records: dict[str, GeoRecord]) -> None:
    # Compact, not indented: indentation cost a measured factor of 4 (RU.geojson:
    # 90 MB indented, 25 MB compact), on versioned files rewritten in full on every
    # decision.
    write_json_atomic(paths.geo, {
        "type": "FeatureCollection",
        "features": [
            _feature_arrondie(records[key].to_feature()) for key in sorted(records)
        ],
    }, indent=None)


def _image_url(meta: dict) -> str | None:
    # Both sources store a path relative to the project root, which the server
    # serves as-is.
    return "/" + meta["image"] if meta.get("image") else None


def build_queue(paths: CountryPaths, include_all: bool = False) -> dict:
    """The country's review queue.

    By default, metas already drawn or rejected are excluded from it. `include_all`
    reopens them with their pieces, to go over a country again when a new source does
    better.
    """
    metas = load_metas(paths)
    geo = load_geo(paths)
    items = []
    queued_ids = set()
    for meta in metas:
        record = geo.get(meta["id"])
        if record is not None and not include_all:
            continue
        queued_ids.add(meta["id"])
        items.append({
            "id": meta["id"],
            "title": meta["title"],
            "description": meta["description"],
            "category": meta["category"],
            "tier": meta["tier"],
            "origin": meta.get("origin", ORIGIN_PLONKIT),
            "image": _image_url(meta),
            "latlon": meta.get("maps_latlon"),
            "source_url": meta.get("source_url", ""),
            "status": record.status if record is not None else None,
            "pieces": record.pieces if record is not None else [],
        })
    # `done` counts the metas already decided but ABSENT from the returned queue,
    # not simply `len(geo)`: by default the two coincide (a decided meta is always
    # excluded from the queue), but under `include_all` everything is reopened and put
    # back in the queue, so `done` falls back to 0. That is what lets the JS caller
    # keep the same `done + current index` formula in both modes, with no special
    # case.
    done = sum(1 for meta_id in geo if meta_id not in queued_ids)
    return {
        "country": paths.country,
        "total": len(metas),
        "done": done,
        "items": items,
    }


def set_decision(
    paths: CountryPaths,
    meta_id: str,
    status: str,
    geometry: dict | None,
    pieces: list[dict],
) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status!r} (expected {' or '.join(STATUSES)})")
    if meta_id not in {meta["id"] for meta in load_metas(paths)}:
        raise UnknownMetaError(f"unknown meta: {meta_id!r}")
    records = load_geo(paths)
    records[meta_id] = GeoRecord(
        id=meta_id, geometry=geometry, pieces=list(pieces), status=status
    )
    save_geo(paths, records)


def clear_decision(paths: CountryPaths, meta_id: str) -> None:
    """Put a meta back in the "to do" state by removing its decision."""
    records = load_geo(paths)
    if meta_id not in records:
        raise UnknownMetaError(f"no decision to undo for {meta_id!r}")
    del records[meta_id]
    save_geo(paths, records)
