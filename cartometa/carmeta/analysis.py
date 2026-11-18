"""Analysis of one country: which file feeds which family, and every tag's fate."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from cartometa.carmeta.footprint import footprint_pieces
from cartometa.carmeta.mirror import KIND_POINTS, CompactFile
from cartometa.carmeta.rules import Rules, analysis_fingerprint
from cartometa.carmeta.tags import (
    FAMILY_CAR_YEAR,
    FAMILY_COPYRIGHT,
    KEPT_FAMILIES,
    Canonical,
    classify,
)
from cartometa.carmeta.verdicts import DROPPED, geometric_verdict
from cartometa.carmeta.zones import (
    REGION_RATIO,
    build_frame,
    cell_states_b64,
    coverage_b64,
    regional_gain,
    representative,
    tag_zones,
)

# A file is a country's *primary* file when the country weighs at least this
# share of its points; failing that a *multi-country* file from this many
# points. The rest is ignored: the Luxembourg file holds 1 626 points in
# Germany, which does not make it a German source.
PRIMARY_SHARE = 0.50
MULTI_MIN_POINTS = 1000

ROLE_PRIMARY = "primary"
ROLE_MULTI = "multi"
ROLE_PINNED = "pinned"

# A finer tag implies a parent when this share of its points carry the parent…
CHILD_INCLUSION = 0.98
# …and the parent is dropped once its children cover this share of its points.
PARENT_COVERAGE = 0.95
MIN_CHILD_POINTS = 5

Loader = Callable[[str], CompactFile]


@dataclass(frozen=True)
class Candidate:
    path: str
    sha: str
    date: str
    role: str
    points: int


def _hex_colour(value) -> str | None:
    """`#rrggbb` from what the files carry: an [r, g, b] list or a hex string."""
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) == 3 and all(c in "0123456789abcdefABCDEF" for c in text):
            text = "".join(c * 2 for c in text)
        if len(text) == 6 and all(c in "0123456789abcdefABCDEF" for c in text):
            return "#" + text.lower()
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            channels = [int(round(float(v))) for v in value[:3]]
        except (TypeError, ValueError):
            return None
        if all(0 <= c <= 255 for c in channels):
            return "#" + "".join(f"{c:02x}" for c in channels)
    return None


class FileCountry:
    """The points of one file that fall in one country, seen through their tags.

    Raw tags are reduced to their canonical form before anything is counted:
    two spellings of the same tag are one tag, and a point carrying both counts
    once.
    """

    def __init__(self, compact: CompactFile, country: str, rules: Rules,
                 iso_codes: frozenset[str]) -> None:
        self.compact = compact
        self.country = country
        self.rules = rules
        self.index = compact.points_of(country)
        lexicon = rules.lexicon_index
        canonical_of_raw = [classify(tag, iso_codes, lexicon) for tag in compact.tags]
        used, self._inverse, self._counts = np.unique(
            compact.combo[self.index], return_inverse=True, return_counts=True)
        self._inverse = self._inverse.ravel()
        self.canonicals: dict[str, Canonical] = {}
        # Canonical text -> local combinations carrying it / raw tag -> points.
        self._combos: dict[str, list[int]] = {}
        self._raw_points: dict[str, dict[str, int]] = {}
        for local, combo in enumerate(used.tolist()):
            seen = set()
            for raw_id in compact.combos[combo]:
                canonical = canonical_of_raw[raw_id]
                if canonical is None:
                    continue
                raw_points = self._raw_points.setdefault(canonical.text, {})
                raw = compact.tags[raw_id]
                raw_points[raw] = raw_points.get(raw, 0) + int(self._counts[local])
                if canonical.text in seen:
                    continue
                seen.add(canonical.text)
                self.canonicals.setdefault(canonical.text, canonical)
                self._combos.setdefault(canonical.text, []).append(local)
        self.points = {
            text: int(self._counts[combos].sum()) for text, combos in self._combos.items()
        }
        self._frame = None

    def families(self, min_points: int) -> set[str]:
        return {self.canonicals[text].family
                for text, count in self.points.items() if count >= min_points}

    @property
    def frame(self):
        if self._frame is None:
            self._frame = build_frame(self.compact.lat[self.index],
                                      self.compact.lng[self.index])
        return self._frame

    def _is_parent(self, text: str) -> bool:
        """Covered by finer `car_year` tags: only the finest level is kept.

        A copyright is never a parent — `©2026` may coincide with `Smallcam
        2026`, they are two different clues — and neither is a `car_year`.
        """
        if self.canonicals[text].family in (FAMILY_COPYRIGHT, FAMILY_CAR_YEAR):
            return False
        mine = set(self._combos[text])
        total = self.points[text]
        covered: set[int] = set()
        for other, combos in self._combos.items():
            if self.canonicals[other].family != FAMILY_CAR_YEAR:
                continue
            size = self.points[other]
            if size >= total or size < MIN_CHILD_POINTS:
                continue
            shared = [k for k in combos if k in mine]
            if sum(int(self._counts[k]) for k in shared) >= CHILD_INCLUSION * size:
                covered.update(shared)
        if not covered:
            return False
        return int(self._counts[sorted(covered)].sum()) >= PARENT_COVERAGE * total

    def grid(self) -> dict:
        frame = self.frame
        return {
            "s": round(frame.cell_km, 3), "W": frame.width, "H": frame.height,
            "D": round(frame.size_km, 1), "R": round(REGION_RATIO * frame.size_km, 1),
            "delta": round(frame.spacing_km, 3), "link": round(frame.link_km, 3),
            "cov": coverage_b64(frame),
        }

    def rows(self, families: set[str]) -> list[dict]:
        thresholds = self.rules.thresholds
        rows = []
        for text in sorted(self._combos, key=lambda t: (-self.points[t], t)):
            canonical = self.canonicals[text]
            if canonical.family not in families:
                continue
            raw_points = self._raw_points[text]
            best_raw = max(raw_points, key=lambda raw: (raw_points[raw], raw))
            count = self.points[text]
            row = {
                "canonical": text, "family": canonical.family,
                "lexicon_key": canonical.lexicon_key, "year": canonical.year,
                "antenna": canonical.antenna, "raw_tags": sorted(raw_points),
                "color": _hex_colour(self.compact.colors.get(best_raw)),
                "points": count, "zones": 0, "capture": 0.0, "gain": None,
                "rep": None, "pieces": None, "cells": None,
            }
            is_parent = False
            zones = None
            if count >= thresholds.min_zone_points:
                is_parent = self._is_parent(text)
                members = np.nonzero(np.isin(self._inverse, self._combos[text]))[0]
                zones = tag_zones(self.frame, members, thresholds.min_zone_points)
                row["zones"] = zones.count
                row["capture"] = round(zones.capture, 4)
                if zones.count:
                    row["gain"] = round(regional_gain(self.frame, zones.points), 4)
            row["verdict"], row["reason"] = geometric_verdict(
                count, is_parent, row["zones"], row["capture"], row["gain"], thresholds)
            # Footprint for every tag the gain lines decided, dropped ones
            # included: an arbitration `keep` must be importable as it is.
            reached_gain = (count >= thresholds.min_zone_points and not is_parent
                            and row["zones"] > 0
                            and row["capture"] >= thresholds.min_capture)
            if reached_gain:
                point = int(self.index[representative(self.frame, zones)])
                row["rep"] = {
                    "lat": round(float(self.compact.lat[point]), 6),
                    "lng": round(float(self.compact.lng[point]), 6),
                    "pano": self.compact.pano[point].decode("utf-8", "replace"),
                    "heading": round(float(self.compact.heading[point]), 1),
                }
                row["pieces"] = footprint_pieces(self.frame, zones)
                row["cells"] = cell_states_b64(self.frame, zones.points)
            rows.append(row)
        return rows


def _points_files(state: dict, rules: Rules):
    excluded = set(rules.exclude)
    for path, entry in sorted(state["files"].items()):
        if entry.get("kind") == KIND_POINTS and path not in excluded:
            yield path, entry


def candidates_for(country: str, state: dict, rules: Rules) -> list[Candidate]:
    """Primary files, newest first; failing any, the richest multi-country file."""
    primaries, multis = [], []
    for path, entry in _points_files(state, rules):
        points = entry.get("countries", {}).get(country, 0)
        if not points:
            continue
        if points >= PRIMARY_SHARE * entry["points"]:
            primaries.append(Candidate(path, entry["sha"], entry["commit_date"],
                                       ROLE_PRIMARY, points))
        elif points >= MULTI_MIN_POINTS:
            multis.append(Candidate(path, entry["sha"], entry["commit_date"],
                                    ROLE_MULTI, points))
    if primaries:
        # Newest commit first; same date, the file with the most points.
        primaries.sort(key=lambda c: c.path)
        primaries.sort(key=lambda c: (c.date, c.points), reverse=True)
        return primaries
    multis.sort(key=lambda c: c.path)
    multis.sort(key=lambda c: c.points, reverse=True)
    return multis[:1]


def _pinned(country: str, family: str, state: dict, rules: Rules) -> Candidate | None:
    path = rules.pin.get(f"{country}|{family}") or rules.pin.get(country)
    if path is None:
        return None
    entry = state["files"].get(path)
    points = (entry or {}).get("countries", {}).get(country, 0)
    if not entry or entry.get("kind") != KIND_POINTS or not points:
        raise ValueError(
            f"rules.json pins {path!r} for {country}, but the mirror holds no "
            f"points of that file in {country}")
    return Candidate(path, entry["sha"], entry["commit_date"], ROLE_PINNED, points)


def served_countries(state: dict, rules: Rules) -> list[str]:
    """Every country at least one file can feed."""
    codes = set()
    for _, entry in _points_files(state, rules):
        codes.update(entry.get("countries", {}))
    served = {code for code in codes if candidates_for(code, state, rules)}
    served.update(key.split("|")[0] for key in rules.pin)
    return sorted(served)


def analyse_country(country: str, state: dict, rules: Rules, load: Loader,
                    iso_codes: frozenset[str]) -> dict:
    """The payload of `analysis/<CC>.json`.

    Per family, the source is the first candidate holding at least one tag of
    that family with enough points for a zone: a new version of a file that
    drops the copyrights does not lose them, they keep coming from the previous
    one.
    """
    minimum = rules.thresholds.min_zone_points
    candidates = candidates_for(country, state, rules)
    views: dict[str, FileCountry] = {}

    def view(candidate: Candidate) -> FileCountry:
        if candidate.path not in views:
            views[candidate.path] = FileCountry(load(candidate.sha), country, rules, iso_codes)
        return views[candidate.path]

    chosen: dict[str, Candidate] = {}
    for family in KEPT_FAMILIES:
        pinned = _pinned(country, family, state, rules)
        if pinned is not None:
            if family in view(pinned).families(minimum):
                chosen[family] = pinned
            continue
        for candidate in candidates:
            if family in view(candidate).families(minimum):
                chosen[family] = candidate
                break

    order: list[Candidate] = []
    for family in KEPT_FAMILIES:
        candidate = chosen.get(family)
        if candidate is not None and candidate not in order:
            order.append(candidate)
    sources, rows = [], []
    for position, candidate in enumerate(order):
        families = {f for f, c in chosen.items() if c == candidate}
        file_country = view(candidate)
        sources.append({
            "path": candidate.path, "sha": candidate.sha, "date": candidate.date,
            "role": candidate.role, "points": candidate.points,
            "families": [f for f in KEPT_FAMILIES if f in families],
            "grid": file_country.grid(),
        })
        for row in file_country.rows(families):
            rows.append({**row, "source": position})
    return {
        "country": country,
        "rules_fingerprint": analysis_fingerprint(rules),
        "sources": sources,
        "rows": rows,
    }


def unused_paths(state: dict, analyses: dict[str, dict]) -> list[str]:
    """Points files that feed no country: shown in the report, never silent."""
    used = {source["path"] for analysis in analyses.values()
            for source in analysis["sources"]}
    return sorted(path for path, entry in state["files"].items()
                  if entry.get("kind") == KIND_POINTS and path not in used)
