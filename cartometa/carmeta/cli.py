from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cartometa.carmeta import github, mirror
from cartometa.carmeta.analysis import unused_paths
from cartometa.carmeta.importer import (
    SKIPPED_REJECTED,
    SKIPPED_VALIDATED,
    UNCHANGED,
    CarmetaImportError,
    ImportPlan,
    run_import,
)
from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.rules import RulesError, load_rules
from cartometa.carmeta.sync import SyncBusy, load_analyses, run_sync
from cartometa.carmeta.verdicts import (
    ARBITRATION,
    DROPPED,
    KEPT,
    effective_verdict,
    pending_cases,
)


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def cmd_sync(args, paths: CarmetaPaths) -> None:
    rules = load_rules(paths.rules)
    try:
        result = run_sync(paths, rules, args.fetch, force=args.force,
                          progress=print if args.verbose else (lambda message: None))
    except SyncBusy as exc:
        print(str(exc))
        return
    except (github.GithubError, ValueError) as exc:
        _fail(f"sync interrompu : {exc}")
    if not result.changed:
        return
    print(f"carmeta : {len(result.new)} nouveau(x), {len(result.modified)} modifié(s), "
          f"{len(result.deleted)} supprimé(s) - {len(result.analysed)} pays analysé(s), "
          f"{result.pending} cas en attente")
    if result.postponed:
        print(f"  reporté(s) au prochain passage : {', '.join(result.postponed)}")


def status_lines(paths: CarmetaPaths) -> list[str]:
    rules = load_rules(paths.rules)
    state = mirror.load_state(paths)
    analyses = load_analyses(paths)
    if not analyses:
        return ["Aucune analyse en cache : lancer `cartometa-carmeta sync`."]
    lines = [f"Dernier passage : {state.get('checked_at') or 'jamais terminé'}"]
    totals = {KEPT: 0, ARBITRATION: 0, DROPPED: 0}
    for country, analysis in analyses.items():
        counts = {KEPT: 0, ARBITRATION: 0, DROPPED: 0}
        for row in analysis["rows"]:
            counts[effective_verdict(row, country, rules)[0]] += 1
        for verdict, count in counts.items():
            totals[verdict] += count
        lines.append(f"  {country}  {counts[KEPT]:3d} retenus  {counts[ARBITRATION]:3d} "
                     f"en arbitrage  {counts[DROPPED]:3d} écartés")
    lines.append(f"Total : {totals[KEPT]} retenus, {totals[ARBITRATION]} en arbitrage, "
                 f"{totals[DROPPED]} écartés sur {len(analyses)} pays")
    cases = pending_cases(analyses, rules)
    if cases:
        lines.append(f"{len(cases)} cas en attente : `cartometa-carmeta arbitrate`")
    unused = unused_paths(state, analyses)
    if unused:
        lines.append("Fichiers qui ne servent aucun pays :")
        lines.extend(f"  - {path}" for path in unused)
    return lines


def cmd_status(args, paths: CarmetaPaths) -> None:
    print("\n".join(status_lines(paths)))


# Listed one by one only when something happens to them; the rest is counted.
_QUIET = (UNCHANGED, SKIPPED_VALIDATED, SKIPPED_REJECTED)


def import_lines(plan: ImportPlan, dry_run: bool) -> list[str]:
    lines = []
    if dry_run:
        lines.append("[dry-run : rien n'est écrit]")
    lines.extend(f"! {warning}" for warning in plan.warnings)
    for country in plan.countries:
        lines.append(f"{country.country}")
        quiet: dict[str, int] = {}
        for action in country.actions:
            if action.kind in _QUIET:
                quiet[action.kind] = quiet.get(action.kind, 0) + 1
                continue
            detail = f" ({action.detail})" if action.detail else ""
            lines.append(f"  {action.meta_id}  {action.title:40.40s} "
                         f"{action.points:7d} pts  {action.kind}{detail}")
        for kind, count in quiet.items():
            lines.append(f"  {count} meta(s) : {kind}")
        if country.waiting:
            lines.append(f"  {country.waiting} tag(s) en attente d'arbitrage, "
                         f"laissé(s) de côté")
        touched = [a for a in country.actions if a.kind not in _QUIET]
        if touched and country.published:
            lines.append("  Car metas déjà publiées (doublons éventuels à rejeter en revue) :")
            lines.extend(f"    {identifier:12s} {origin:8s} {title}"
                         for identifier, origin, title in country.published)
    return lines


def cmd_import(args, paths: CarmetaPaths) -> None:
    rules = load_rules(paths.rules)
    try:
        plan = run_import(paths.data, args.countries or None, rules, dry_run=args.dry_run)
    except CarmetaImportError as exc:
        _fail(str(exc))
    print("\n".join(import_lines(plan, args.dry_run)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cartometa-carmeta",
        description="Tire des metas `car` proposées des JSON du repo carmeta.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)

    sync = commands.add_parser(
        "sync", help="surveille le repo et refait l'analyse (commande planifiée)")
    sync.add_argument("--force", action="store_true",
                      help="refait l'analyse même sans changement du repo "
                           "(apres une modification des règles)")
    sync.add_argument("--verbose", action="store_true",
                      help="affiche chaque téléchargement et chaque pays analysé")
    sync.set_defaults(run=cmd_sync)

    importer = commands.add_parser(
        "import", help="écrit les tags retenus comme metas proposées, à valider "
                       "dans cartometa-review")
    importer.add_argument("countries", nargs="*", metavar="CC",
                          help="codes pays ; par défaut, tous les pays analysés")
    importer.add_argument("--dry-run", action="store_true",
                          help="affiche ce qui serait fait sans rien écrire")
    importer.set_defaults(run=cmd_import)

    status = commands.add_parser("status", help="résumé de l'analyse en cache")
    status.set_defaults(run=cmd_status)
    return parser


def main(argv: list[str] | None = None, fetch: github.Fetch = github.urllib_fetch) -> None:
    args = build_parser().parse_args(argv)
    args.fetch = fetch
    try:
        args.run(args, CarmetaPaths(args.data_dir))
    except RulesError as exc:
        _fail(str(exc))


if __name__ == "__main__":
    main()
