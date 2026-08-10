from __future__ import annotations

import argparse
from pathlib import Path

from cartometa.extract.categories import CATEGORIES
from cartometa.tagged.importer import ImportReport, TaggedFileError, import_tagged


def _print_report(report: ImportReport, dry_run: bool) -> None:
    dropped = ""
    if report.untagged or report.unplaced:
        dropped = (f", {report.untagged} sans tag, "
                   f"{report.unplaced} hors de tout pays")
    header = f"{report.source} — mode {report.mode}{dropped}"
    if dry_run:
        header += "  [dry-run : rien n'est écrit]"
    print(header)
    for row in sorted(report.rows, key=lambda r: (r.tag, r.country)):
        print(f"  {row.tag:40s} {row.country}  {row.points:5d} pts "
              f"-> {row.pieces:3d} pièce(s)   {row.action}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="cartometa-import-tagged",
        description="Transforme un JSON de points taggés (format carte GeoGuessr) "
                    "en metas proposées, à valider dans cartometa-review.",
    )
    parser.add_argument("file", type=Path, help="le JSON de points taggés")
    parser.add_argument("--mode", required=True, choices=("route", "zone"),
                        help="corridor fidèle (route) ou enveloppe concave (zone)")
    parser.add_argument("--category", required=True,
                        help=f"catégorie des metas produites ({', '.join(CATEGORIES)})")
    parser.add_argument("--buffer-m", type=float, default=250.0,
                        help="demi-largeur du corridor en mètres (défaut 250)")
    parser.add_argument("--link-km", type=float, default=None,
                        help="seuil de chaînage en km (défaut 5 en route, 40 en zone)")
    parser.add_argument("--hull-buffer-km", type=float, default=10.0,
                        help="gonflement de l'enveloppe en km (défaut 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="calcule et affiche le récapitulatif sans rien écrire")
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.category not in CATEGORIES:
        parser.error(f"unknown category: {args.category!r} "
                     f"(expected {', '.join(CATEGORIES)})")
    try:
        report = import_tagged(
            args.data_dir, args.file, mode=args.mode, category=args.category,
            buffer_m=args.buffer_m, link_km=args.link_km,
            hull_buffer_km=args.hull_buffer_km, dry_run=args.dry_run,
        )
    except TaggedFileError as exc:
        raise SystemExit(str(exc)) from None
    _print_report(report, args.dry_run)


if __name__ == "__main__":
    main()
