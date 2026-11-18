"""`cartometa-carmeta import`: retained tags become proposed metas.

Split in two on purpose. `plan_import` reads everything and writes nothing: it
is what `--dry-run`, `status` and the report call. `apply_import` writes what
the plan decided, and only the files a decision actually changes — a second
import with nothing new must not touch a byte.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from cartometa.atomic_write import write_json_atomic
from cartometa.carmeta.footprint import iou, pieces_geometry
from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.rules import Rules, analysis_fingerprint
from cartometa.carmeta.sync import load_analyses
from cartometa.carmeta.tags import classify
from cartometa.carmeta.texts import SOURCE_URL, description, maps_url, meta_id, title
from cartometa.carmeta.verdicts import ARBITRATION, KEPT, effective_verdict
from cartometa.models import (
    ORIGIN_CARMETA,
    ORIGIN_PLONKIT,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    STATUS_TRACED,
    TIER_MANUAL,
    GeoRecord,
)
from cartometa.review.server import DEFAULT_PORT as REVIEW_PORT
from cartometa.review.server import port_is_taken
from cartometa.review.store import (
    CountryPaths,
    load_geo,
    load_metas,
    read_json_list,
    same_pieces,
    save_geo,
)

CATEGORY = "car"

WRITTEN = "écrite"
REWRITTEN = "réécrite"
UNCHANGED = "inchangée"
RETEXTED = "texte mis à jour"
SKIPPED_REJECTED = "rejetée, jamais re-proposée"
SKIPPED_VALIDATED = "validée, empreinte stable"
REPROPOSED = "re-proposée"
VANISHED_KEPT = "disparue, conservée"
VANISHED_DELETED = "disparue, supprimée"
WAITING = "en attente d'arbitrage, conservée"

ABSENT = "tag absent du fichier"


class CarmetaImportError(ValueError):
    """Import refused: nothing was written."""


@dataclass
class Action:
    country: str
    meta_id: str
    canonical: str
    title: str
    kind: str
    points: int = 0
    detail: str = ""


@dataclass
class CountryPlan:
    country: str
    actions: list[Action] = field(default_factory=list)
    metas: dict[str, dict] = field(default_factory=dict)
    records: dict[str, GeoRecord] = field(default_factory=dict)
    texts_changed: bool = False
    geo_changed: bool = False
    # Retained-looking tags left aside because their arbitration is pending.
    waiting: int = 0
    # Car metas already published in the country, every origin: (id, origin, title).
    published: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.texts_changed or self.geo_changed


@dataclass
class ImportPlan:
    countries: list[CountryPlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def actions(self) -> list[Action]:
        return [action for country in self.countries for action in country.actions]


def _rounded(value):
    if isinstance(value, float):
        return round(value, 5)
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    return value


def baseline_of(geometry: BaseGeometry) -> dict:
    """The computed footprint as stored for the next comparison.

    Always a MultiPolygon, rounded like the pieces it comes from: two imports
    of the same analysis store the same bytes.
    """
    polygons = [geometry] if geometry.geom_type == "Polygon" else [
        g for g in getattr(geometry, "geoms", []) if g.geom_type == "Polygon"]
    return {"type": "MultiPolygon",
            "coordinates": [_rounded(mapping(p)["coordinates"]) for p in polygons]}


def _texts(carmeta: dict, rules: Rules) -> tuple[str, str]:
    """Title and description from a stored `carmeta` block and today's lexicon."""
    canonical = classify(carmeta["canonical"], frozenset(), rules.lexicon_index)
    row = {"family": carmeta["family"], "lexicon_key": canonical.lexicon_key,
           "year": canonical.year, "antenna": canonical.antenna}
    return title(row, rules), description(row, rules, carmeta["points"])


def _build_meta(country: str, identifier: str, row: dict, source: dict,
                geometry: BaseGeometry, rules: Rules, extracted_at: str) -> dict:
    carmeta = {
        "canonical": row["canonical"], "family": row["family"],
        "raw_tags": row["raw_tags"], "source_path": source["path"],
        "source_sha": source["sha"], "source_date": source["date"][:10],
        "points": row["points"], "zones": row["zones"],
        "capture": row["capture"], "gain": row["gain"],
    }
    # Absent rather than null, like the difficulty of a manual meta.
    if row.get("color"):
        carmeta["color"] = row["color"]
    carmeta["baseline"] = baseline_of(geometry)
    rep = row["rep"]
    return {
        "id": identifier, "country": country, "tier": TIER_MANUAL,
        "origin": ORIGIN_CARMETA, "category": CATEGORY,
        "title": title(row, rules),
        "description": description(row, rules, row["points"]),
        "description_origin": "generated", "source_url": SOURCE_URL,
        # Kept across runs: two identical imports must be byte-identical.
        "extracted_at": extracted_at, "image": None,
        "maps_url": maps_url(rep, rules.streetview_pitch),
        "maps_latlon": [rep["lat"], rep["lng"]],
        "carmeta": carmeta,
    }


def _published_car_metas(paths: CountryPaths, records: dict[str, GeoRecord],
                         data_dir: Path) -> list[tuple[str, str, str]]:
    overrides_path = data_dir / "categories.json"
    overrides = {}
    if overrides_path.exists():
        overrides = json.loads(overrides_path.read_text("utf-8")).get(paths.country, {})
    published = []
    for meta in load_metas(paths):
        record = records.get(meta["id"])
        if record is None or record.status != STATUS_TRACED:
            continue
        if overrides.get(meta["id"], meta.get("category")) == CATEGORY:
            published.append((meta["id"], meta.get("origin", ORIGIN_PLONKIT),
                              meta["title"]))
    return published


def plan_country(data_dir: Path, analysis: dict, rules: Rules, now: str) -> CountryPlan:
    country = analysis["country"]
    paths = CountryPaths(data_dir, country)
    records = load_geo(paths)
    stored = {meta["id"]: meta for meta in read_json_list(paths.carmeta_metas)}
    plan = CountryPlan(country=country, metas=dict(stored), records=records)
    plan.published = _published_car_metas(paths, records, data_dir)

    verdicts = {row["canonical"]: effective_verdict(row, country, rules)
                for row in analysis["rows"]}
    plan.waiting = sum(1 for verdict, _ in verdicts.values() if verdict == ARBITRATION)
    retained: dict[str, dict] = {}
    for row in analysis["rows"]:
        if verdicts[row["canonical"]][0] != KEPT:
            continue
        identifier = meta_id(country, row["canonical"])
        if identifier in retained:
            raise CarmetaImportError(
                f"id collision in {country}: {retained[identifier]['canonical']!r} and "
                f"{row['canonical']!r} both give {identifier}")
        retained[identifier] = row

    for identifier, row in sorted(retained.items(), key=lambda kv: kv[1]["canonical"]):
        source = analysis["sources"][row["source"]]
        pieces = row["pieces"]
        geometry = pieces_geometry(pieces)
        existing = records.get(identifier)
        previous = stored.get(identifier)
        meta = _build_meta(country, identifier, row, source, geometry, rules,
                           (previous or {}).get("extracted_at", now))

        def act(kind: str, detail: str = "", shown: dict = meta) -> None:
            plan.actions.append(Action(country, identifier, row["canonical"],
                                       shown["title"], kind, row["points"], detail))

        if existing is None or existing.status == STATUS_PROPOSED:
            if (existing is not None and previous == meta
                    and same_pieces(existing.pieces, pieces)):
                act(UNCHANGED)
                continue
            act(WRITTEN if existing is None else REWRITTEN)
            plan.metas[identifier] = meta
            records[identifier] = GeoRecord(id=identifier, geometry=None,
                                            pieces=pieces, status=STATUS_PROPOSED)
            plan.texts_changed = plan.geo_changed = True
            continue
        if existing.status == STATUS_REJECTED:
            # A rejection is final: neither the footprint nor the text moves.
            act(SKIPPED_REJECTED, shown=previous or meta)
            continue
        # Validated. Compared with the *baseline* — the last computed footprint
        # shown to the maintainer — never with the validated geometry: had it
        # been retouched by hand, the gap would be permanent and the meta would
        # come back on every run.
        baseline = (previous or {}).get("carmeta", {}).get("baseline")
        if previous is None or baseline is None:
            # Validated footprint whose text was lost: the text is rebuilt, the
            # footprint is the maintainer's and stays.
            act(RETEXTED, "texte reconstruit")
            plan.metas[identifier] = meta
            plan.texts_changed = True
            continue
        overlap = iou(geometry, shape(baseline))
        if overlap >= rules.thresholds.reproposal_iou:
            # Footprint stable: the stored figures stay, but a label corrected
            # in the lexicon must still reach a validated meta.
            new_title, new_description = _texts(previous["carmeta"], rules)
            if (new_title, new_description) == (previous["title"], previous["description"]):
                act(SKIPPED_VALIDATED, f"recouvrement {overlap:.0%}", shown=previous)
                continue
            plan.metas[identifier] = {**previous, "title": new_title,
                                      "description": new_description}
            plan.texts_changed = True
            act(RETEXTED, shown=plan.metas[identifier])
            continue
        # The meta stays published as validated; the new footprint waits next
        # to it until the review adopts or dismisses it.
        act(REPROPOSED, f"recouvrement {overlap:.0%}")
        plan.metas[identifier] = meta
        existing.proposal = {"pieces": pieces}
        plan.texts_changed = plan.geo_changed = True

    for identifier, previous in sorted(stored.items()):
        if identifier in retained:
            continue
        canonical = previous.get("carmeta", {}).get("canonical", "")
        verdict, reason = verdicts.get(canonical, (None, ABSENT))
        existing = records.get(identifier)
        status = existing.status if existing is not None else None

        def act(kind: str) -> None:
            plan.actions.append(Action(
                country, identifier, canonical, previous["title"], kind,
                previous.get("carmeta", {}).get("points", 0), reason))

        if status == STATUS_REJECTED:
            # Text and rejection both stay, or the rejection would not be final.
            continue
        if verdict == ARBITRATION:
            # Not gone: its fate hangs on a pending decision.
            act(WAITING)
            continue
        if status == STATUS_TRACED:
            act(VANISHED_KEPT)
            if existing.proposal is not None:
                # A newer footprint the data no longer supports.
                existing.proposal = None
                plan.geo_changed = True
            continue
        act(VANISHED_DELETED)
        del plan.metas[identifier]
        plan.texts_changed = True
        if existing is not None:
            del records[identifier]
            plan.geo_changed = True
    return plan


def plan_import(data_dir: Path, countries: list[str] | None, rules: Rules,
                now: str | None = None) -> ImportPlan:
    """What an import would do. Reads only."""
    carmeta_paths = CarmetaPaths(data_dir)
    analyses = load_analyses(carmeta_paths)
    if not analyses:
        raise CarmetaImportError(
            "aucune analyse en cache : lancer `cartometa-carmeta sync` d'abord.")
    now = now or datetime.now(timezone.utc).isoformat()
    plan = ImportPlan()
    with_texts = {path.stem for path in (data_dir / "carmeta").glob("??.json")} \
        if (data_dir / "carmeta").exists() else set()
    wanted = sorted(set(analyses) | with_texts) if not countries else [
        code.upper() for code in countries]
    fingerprint = analysis_fingerprint(rules)
    for country in wanted:
        analysis = analyses.get(country)
        if analysis is None:
            # No analysis is no evidence: a partly wiped cache must never read
            # as "every tag of this country is gone".
            plan.warnings.append(
                f"{country} : aucune analyse en cache, pays ignoré"
                + (" (ses metas carmeta sont conservées)" if country in with_texts else ""))
            continue
        if analysis.get("rules_fingerprint") != fingerprint:
            raise CarmetaImportError(
                f"{country} : l'analyse en cache a été faite avec d'autres seuils ou "
                f"d'autres sources que rules.json. Lancer `cartometa-carmeta sync --force`.")
        plan.countries.append(plan_country(data_dir, analysis, rules, now))
    return plan


def apply_import(data_dir: Path, plan: ImportPlan) -> None:
    for country in plan.countries:
        paths = CountryPaths(data_dir, country.country)
        if country.texts_changed:
            if country.metas:
                write_json_atomic(paths.carmeta_metas,
                                  [country.metas[key] for key in sorted(country.metas)])
            else:
                paths.carmeta_metas.unlink(missing_ok=True)
        if country.geo_changed:
            save_geo(paths, country.records)


def run_import(data_dir: Path, countries: list[str] | None, rules: Rules, *,
               dry_run: bool = False, now: str | None = None) -> ImportPlan:
    if not dry_run and port_is_taken("127.0.0.1", REVIEW_PORT):
        # The review server rewrites data/geo as decisions land: importing
        # under it would interleave two writers on the same files.
        raise CarmetaImportError(
            f"une session cartometa-review semble active (le port {REVIEW_PORT} "
            f"répond) : les deux écrivent data/geo, arrêtez-la avant d'importer.")
    plan = plan_import(data_dir, countries, rules, now)
    if not dry_run:
        apply_import(data_dir, plan)
    return plan
