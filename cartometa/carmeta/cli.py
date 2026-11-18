from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from cartometa.carmeta import github
from cartometa.carmeta.accept import run_accept
from cartometa.carmeta.arbitrate import ArbitrationError, run_arbitrate
from cartometa.carmeta.importer import (
    SKIPPED_REJECTED,
    SKIPPED_VALIDATED,
    UNCHANGED,
    CarmetaImportError,
    ImportPlan,
    run_import,
)
from cartometa.carmeta.notify import notify
from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.prune import run_prune
from cartometa.carmeta.report import build_report, headline, summary_lines, write_report
from cartometa.carmeta.rules import RulesError, load_rules
from cartometa.carmeta.sync import SyncBusy, run_sync

LOG_NAME = "carmeta-sync.log"


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def _log(logs_dir: Path, message: str) -> None:
    """One line per useful run: with the report, the reliable trace of a sync."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(logs_dir / LOG_NAME, "a", encoding="utf-8") as stream:
        stream.write(f"{stamp} {message}\n")


def cmd_sync(args, paths: CarmetaPaths) -> None:
    rules = load_rules(paths.rules)
    try:
        result = run_sync(paths, rules, args.fetch, force=args.force,
                          progress=print if args.verbose else (lambda message: None))
    except SyncBusy as exc:
        print(str(exc))
        return
    except (github.GithubError, ValueError) as exc:
        _log(args.logs_dir, f"ERREUR {exc}")
        _fail(f"sync interrompu : {exc}")
    if not result.changed:
        # Nothing new in the repository: silent, exit code 0, nothing written.
        return
    report = write_report(paths, rules, result)
    changes = (f"{len(result.new)} nouveau(x), {len(result.modified)} modifié(s), "
               f"{len(result.deleted)} supprimé(s)")
    line = f"{changes} - {headline(report)}"
    _log(args.logs_dir, line)
    print(f"carmeta : {line}")
    if result.postponed:
        print(f"  reporté(s) au prochain passage : {', '.join(result.postponed)}")
    print(f"  rapport : {paths.report}")
    notify("carmeta", f"{changes}. {headline(report)}")


def cmd_status(args, paths: CarmetaPaths) -> None:
    rules = load_rules(paths.rules)
    print("\n".join(summary_lines(build_report(paths, rules))))


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


def cmd_arbitrate(args, paths: CarmetaPaths) -> None:
    try:
        run_arbitrate(paths, input, print)
    except ArbitrationError as exc:
        _fail(str(exc))


def cmd_prune(args, paths: CarmetaPaths) -> None:
    rules = load_rules(paths.rules)
    try:
        run_prune(paths.data, args.countries or None, rules, input, print,
                  assume_yes=args.yes)
    except CarmetaImportError as exc:
        _fail(str(exc))


def cmd_accept(args, paths: CarmetaPaths) -> None:
    try:
        result = run_accept(paths.data, args.countries or None, print)
    except CarmetaImportError as exc:
        _fail(str(exc))
    for country, identifier, title, reason in result.failed:
        print(f"! {country}  {identifier}  {title} : non validée ({reason})")
    print(f"{len(result.accepted)} proposition(s) validée(s), {len(result.adopted)} "
          f"re-proposition(s) adoptée(s), {len(result.failed)} laissée(s) en l'état.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cartometa-carmeta",
        description="Tire des metas `car` proposées des JSON du repo carmeta.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help=argparse.SUPPRESS)
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"),
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

    accept = commands.add_parser(
        "accept", help="valide en lot les propositions carmeta telles que "
                       "calculées, sans passer par la revue")
    accept.add_argument("countries", nargs="*", metavar="CC",
                        help="codes pays ; par défaut, tous les pays importés")
    accept.set_defaults(run=cmd_accept)

    arbitrate = commands.add_parser(
        "arbitrate", help="tranche les cas limites du filtre, une fois pour toutes")
    arbitrate.set_defaults(run=cmd_arbitrate)

    prune = commands.add_parser(
        "prune", help="supprime, après confirmation, les metas validées dont le "
                      "tag a disparu")
    prune.add_argument("countries", nargs="*", metavar="CC",
                       help="codes pays ; par défaut, tous les pays analysés")
    prune.add_argument("--yes", action="store_true",
                       help="supprime sans demander confirmation")
    prune.set_defaults(run=cmd_prune)

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
