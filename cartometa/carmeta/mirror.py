"""Local mirror of the carmeta files: what changed, and a compact copy of each.

The raw JSON files weigh about 1.3 GB and are never kept: each one is reduced
to the arrays the analysis reads (`files/<blob sha>.npz`), with the country of
every point computed once.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import numpy as np

from cartometa.atomic_write import write_json_atomic
from cartometa.carmeta.countries import CountryAssigner
from cartometa.carmeta.github import Tree
from cartometa.carmeta.paths import CarmetaPaths

KIND_POINTS = "points"
KIND_OTHER = "other"

# Never points: skipped without a download. Everything else is fetched once
# and recognised by its content — a points file may have no extension at all.
_SKIPPED_SUFFIXES = frozenset({
    ".md", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".py",
    ".yml", ".yaml", ".html", ".css", ".js", ".toml", ".lock",
})
# The separators of some files are carried by dummy points near the pole.
MAX_ABS_LATITUDE = 84.0


def is_candidate(path: str) -> bool:
    pure = PurePosixPath(path)
    if len(pure.parts) < 2 or any(part.startswith(".") for part in pure.parts):
        return False
    return pure.suffix.lower() not in _SKIPPED_SUFFIXES


def load_state(paths: CarmetaPaths) -> dict:
    if not paths.state.exists():
        return {"tree_sha": None, "checked_at": None, "dirty": [], "files": {}}
    state = json.loads(paths.state.read_text("utf-8"))
    state.setdefault("dirty", [])
    state.setdefault("files", {})
    return state


def save_state(paths: CarmetaPaths, state: dict) -> None:
    state["dirty"] = sorted(set(state.get("dirty", [])))
    state["files"] = dict(sorted(state["files"].items()))
    write_json_atomic(paths.state, state)


@dataclass
class Diff:
    new: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def to_fetch(self) -> list[str]:
        return sorted(self.new + self.modified)

    def __bool__(self) -> bool:
        return bool(self.new or self.modified or self.deleted)


def diff(state: dict, tree: Tree) -> Diff:
    known = state["files"]
    result = Diff()
    for path, blob in sorted(tree.blobs.items()):
        if not is_candidate(path):
            continue
        if path not in known:
            result.new.append(path)
        elif known[path]["sha"] != blob.sha:
            result.modified.append(path)
    result.deleted = sorted(path for path in known if path not in tree.blobs)
    return result


@dataclass
class CompactFile:
    """One carmeta file, reduced to what the analysis reads.

    Tags are stored through *combinations*: a file holds hundreds of thousands
    of points but only a few hundred distinct sets of tags.
    """

    name: str
    lat: np.ndarray
    lng: np.ndarray
    heading: np.ndarray
    pano: np.ndarray
    combo: np.ndarray
    country: np.ndarray
    tags: list[str]
    combos: list[list[int]]
    colors: dict[str, object]
    order: dict[str, object]
    codes: list[str]

    def country_counts(self) -> dict[str, int]:
        placed = self.country[self.country >= 0]
        counts = np.bincount(placed, minlength=len(self.codes))
        return {self.codes[i]: int(n) for i, n in enumerate(counts) if n}

    def points_of(self, code: str) -> np.ndarray:
        if code not in self.codes:
            return np.zeros(0, dtype=np.int64)
        return np.nonzero(self.country == self.codes.index(code))[0]


def _json_payload(raw: bytes):
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = [name for name in archive.namelist()
                           if not name.startswith("__MACOSX") and not name.endswith("/")]
                if not members:
                    return None
                raw = archive.read(members[0])
        except zipfile.BadZipFile:
            return None
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None


def decode_points(raw: bytes, assigner: CountryAssigner) -> CompactFile | None:
    """The compact form of a downloaded blob, or None when it holds no points.

    The format is recognised by content, never by name: a `.zip` holds one
    JSON, and a file with no extension can be a JSON too.
    """
    payload = _json_payload(raw)
    if not isinstance(payload, dict):
        return None
    coordinates = payload.get("customCoordinates")
    if not isinstance(coordinates, list):
        return None
    lat, lng, heading, pano, combo = [], [], [], [], []
    tag_ids: dict[str, int] = {}
    combo_ids: dict[tuple[int, ...], int] = {}
    for entry in coordinates:
        if not isinstance(entry, dict) or not entry.get("panoId"):
            continue
        try:
            point_lat, point_lng = float(entry["lat"]), float(entry["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(point_lat) >= MAX_ABS_LATITUDE:
            continue
        extra = entry.get("extra") or {}
        tags = extra.get("tags") if isinstance(extra, dict) else None
        key = tuple(sorted({
            tag_ids.setdefault(str(tag), len(tag_ids)) for tag in (tags or [])
        }))
        lat.append(point_lat)
        lng.append(point_lng)
        try:
            heading.append(float(entry.get("heading") or 0.0))
        except (TypeError, ValueError):
            heading.append(0.0)
        pano.append(str(entry["panoId"]))
        combo.append(combo_ids.setdefault(key, len(combo_ids)))
    lat_array, lng_array = np.array(lat, dtype=np.float64), np.array(lng, dtype=np.float64)
    assigned = assigner.assign(lat_array, lng_array)
    # Country indexes are local to the file: the mirror must not depend on the
    # order of the Natural Earth dataset.
    present = sorted({assigner.codes[i] for i in np.unique(assigned[assigned >= 0])})
    local = np.full(len(assigner.codes) + 1, -1, dtype=np.int32)
    for position, code in enumerate(present):
        local[assigner.codes.index(code)] = position
    declared = (payload.get("extra") or {}).get("tags")
    declared = declared if isinstance(declared, dict) else {}
    tags = [None] * len(tag_ids)
    for tag, position in tag_ids.items():
        tags[position] = tag
    combos = [None] * len(combo_ids)
    for key, position in combo_ids.items():
        combos[position] = list(key)
    return CompactFile(
        name=str(payload.get("name") or ""),
        lat=lat_array, lng=lng_array,
        heading=np.array(heading, dtype=np.float32),
        pano=np.array(pano, dtype="S") if pano else np.zeros(0, dtype="S1"),
        combo=np.array(combo, dtype=np.int32),
        country=local[assigned],
        tags=tags, combos=combos,
        colors={t: m.get("color") for t, m in declared.items()
                if isinstance(m, dict) and m.get("color") is not None},
        order={t: m.get("order") for t, m in declared.items()
               if isinstance(m, dict) and m.get("order") is not None},
        codes=present,
    )


def store_compact(paths: CarmetaPaths, sha: str, compact: CompactFile) -> None:
    paths.files.mkdir(parents=True, exist_ok=True)
    meta = json.dumps({
        "name": compact.name, "tags": compact.tags, "combos": compact.combos,
        "colors": compact.colors, "order": compact.order, "codes": compact.codes,
    }, ensure_ascii=False)
    destination = paths.compact(sha)
    temporary = destination.with_suffix(".npz.tmp")
    with open(temporary, "wb") as handle:
        np.savez_compressed(
            handle, lat=compact.lat, lng=compact.lng, heading=compact.heading,
            pano=compact.pano, combo=compact.combo, country=compact.country,
            meta=np.array(meta),
        )
    os.replace(temporary, destination)


def load_compact(paths: CarmetaPaths, sha: str) -> CompactFile:
    with np.load(paths.compact(sha), allow_pickle=False) as archive:
        meta = json.loads(str(archive["meta"]))
        return CompactFile(
            name=meta["name"], lat=archive["lat"], lng=archive["lng"],
            heading=archive["heading"], pano=archive["pano"],
            combo=archive["combo"], country=archive["country"],
            tags=meta["tags"], combos=meta["combos"], colors=meta["colors"],
            order=meta["order"], codes=meta["codes"],
        )


def file_entry(sha: str, commit_date: str, fetched_at: str,
               compact: CompactFile | None) -> dict:
    """The state.json record of a downloaded blob."""
    if compact is None:
        return {"sha": sha, "commit_date": commit_date, "fetched_at": fetched_at,
                "kind": KIND_OTHER}
    return {"sha": sha, "commit_date": commit_date, "fetched_at": fetched_at,
            "kind": KIND_POINTS, "name": compact.name, "points": int(len(compact.lat)),
            "countries": compact.country_counts()}
