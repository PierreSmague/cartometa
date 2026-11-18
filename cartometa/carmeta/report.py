"""The report of a sync: one self-contained HTML page, and its text summary.

Built from the cached analysis, the rules and — read only — the current state
of data/geo and data/carmeta: the page says what an import *would* do. `status`
prints the same counters, from the same data.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cartometa.carmeta import mirror
from cartometa.carmeta.analysis import unused_paths
from cartometa.carmeta.importer import (
    REPROPOSED,
    RETEXTED,
    REWRITTEN,
    VANISHED_DELETED,
    VANISHED_KEPT,
    WRITTEN,
    CarmetaImportError,
    plan_import,
)
from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.rules import Rules
from cartometa.carmeta.sync import SyncResult, load_analyses
from cartometa.carmeta.texts import maps_url, title
from cartometa.carmeta.verdicts import (
    ARBITRATION,
    DROPPED,
    KEPT,
    KIND_DESCRIPTOR,
    effective_verdict,
    pending_cases,
    reaches_gain,
)

TEMPLATE = Path(__file__).with_name("report_template.html")
# What an import would write, as opposed to what it would leave alone.
TO_IMPORT = (WRITTEN, REWRITTEN, REPROPOSED, RETEXTED)
VANISHED = (VANISHED_KEPT, VANISHED_DELETED)


def build_report(paths: CarmetaPaths, rules: Rules,
                 result: SyncResult | None = None, now: str | None = None) -> dict:
    analyses = load_analyses(paths)
    state = mirror.load_state(paths)
    warnings: list[str] = []
    actions: dict[tuple[str, str], object] = {}
    vanished = []
    try:
        plan = plan_import(paths.data, None, rules)
    except CarmetaImportError as exc:
        # The page is still worth having: it then shows the analysis alone.
        warnings.append(str(exc))
    else:
        warnings.extend(plan.warnings)
        for action in plan.actions:
            actions[(action.country, action.canonical)] = action
            if action.kind in VANISHED:
                vanished.append({"cc": action.country, "title": action.title,
                                 "tag": action.canonical, "kind": action.kind,
                                 "why": action.detail})
    grids, rows, countries = {}, [], {}
    for country, analysis in analyses.items():
        counts = {KEPT: 0, ARBITRATION: 0, DROPPED: 0, "import": 0, "moved": 0,
                  "vanished": sum(1 for v in vanished if v["cc"] == country)}
        for position, source in enumerate(analysis["sources"]):
            grid = source["grid"]
            grids[f"{country}|{position}"] = {
                "W": grid["W"], "H": grid["H"], "s": grid["s"], "R": grid["R"],
                "link": grid["link"], "cov": grid["cov"],
                "file": source["path"].split("/")[-1], "date": source["date"][:10],
                "role": source["role"], "pts": source["points"],
            }
        for row in analysis["rows"]:
            verdict, reason = effective_verdict(row, country, rules)
            counts[verdict] += 1
            action = actions.get((country, row["canonical"]))
            kind = action.kind if action is not None else ""
            if kind in TO_IMPORT:
                counts["import"] += 1
            if kind == REPROPOSED:
                counts["moved"] += 1
            if not reaches_gain(row):
                continue        # no footprint, no map: counted, not drawn
            rows.append({
                "cc": country, "g": f"{country}|{row['source']}", "t": row["canonical"],
                "title": title(row, rules), "n": row["points"], "z": row["zones"],
                "cap": row["capture"], "gain": row["gain"], "v": verdict, "why": reason,
                "act": kind, "det": action.detail if action is not None else "",
                "m": row["cells"],
                "sv": maps_url(row["rep"], rules.streetview_pitch),
            })
        countries[country] = counts
    cases = pending_cases(analyses, rules)
    return {
        "generated_at": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checked_at": state.get("checked_at"),
        "changes": None if result is None else {
            "new": result.new, "modified": result.modified,
            "deleted": result.deleted, "postponed": result.postponed},
        "countries": countries, "grids": grids, "rows": rows, "vanished": vanished,
        "descriptors": [{"key": case["key"],
                         "tags": [f"{t['country']} {t['canonical']}" for t in case["tags"]]}
                        for case in cases if case["kind"] == KIND_DESCRIPTOR],
        "pending": len(cases),
        "unused": unused_paths(state, analyses),
        "warnings": warnings,
    }


def render_report(report: dict) -> str:
    """The page, data embedded: it opens offline, from the file system."""
    # Tags come from third-party files. Inside a script block `</script` closes
    # it and `<!--` changes how the rest is parsed: no `<` is left in the data
    # at all, written as the JSON escape it is.
    payload = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c")
    return TEMPLATE.read_text("utf-8").replace("__DATA__", payload)


def write_report(paths: CarmetaPaths, rules: Rules, result: SyncResult | None = None) -> dict:
    report = build_report(paths, rules, result)
    paths.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.report.with_suffix(".html.tmp")
    temporary.write_text(render_report(report), "utf-8")
    temporary.replace(paths.report)
    return report


def totals(report: dict) -> dict:
    keys = (KEPT, ARBITRATION, DROPPED, "import", "moved", "vanished")
    return {key: sum(counts[key] for counts in report["countries"].values())
            for key in keys}


def headline(report: dict) -> str:
    """One line for the log and the notification."""
    total = totals(report)
    return (f"{total['import']} meta(s) à importer, {report['pending']} cas en attente, "
            f"{total['moved']} empreinte(s) validée(s) qui ont bougé, "
            f"{total['vanished']} tag(s) disparu(s)")


def summary_lines(report: dict) -> list[str]:
    if not report["countries"]:
        return ["Aucune analyse en cache : lancer `cartometa-carmeta sync`."]
    lines = [f"Dernier passage : {report['checked_at'] or 'jamais terminé'}"]
    lines.extend(f"! {warning}" for warning in report["warnings"])
    for country, counts in report["countries"].items():
        extras = "".join(
            f"  {counts[key]} {label}" for key, label in (
                ("import", "à importer"), ("moved", "empreinte(s) à revoir"),
                ("vanished", "disparu(s)")) if counts[key])
        lines.append(f"  {country}  {counts[KEPT]:3d} retenus  {counts[ARBITRATION]:3d} "
                     f"en arbitrage  {counts[DROPPED]:3d} écartés{extras}")
    total = totals(report)
    lines.append(f"Total : {total[KEPT]} retenus, {total[ARBITRATION]} en arbitrage, "
                 f"{total[DROPPED]} écartés sur {len(report['countries'])} pays")
    lines.append(headline(report))
    if report["pending"]:
        lines.append("  -> `cartometa-carmeta arbitrate` pour trancher les cas en attente")
    if total["import"]:
        lines.append("  -> `cartometa-carmeta import` pour écrire les propositions")
    if any(v["kind"] == VANISHED_KEPT for v in report["vanished"]):
        lines.append("  -> `cartometa-carmeta prune` pour supprimer les metas validées "
                     "dont le tag a disparu")
    if report["descriptors"]:
        lines.append("Descripteurs inconnus : "
                     + ", ".join(d["key"] for d in report["descriptors"]))
    if report["unused"]:
        lines.append("Fichiers qui ne servent aucun pays :")
        lines.extend(f"  - {path}" for path in report["unused"])
    return lines
