"""Re-infer the stored category of every meta with the current rules.

`data/metas/` is regenerable, but re-extracting 100 countries to pick up a rule
change would need every saved HTML page and the Maps link cache. Rewriting the
stored category in place is the same result in seconds.

Reports by default; only writes with `--apply`.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
from pathlib import Path

from cartometa.extract.categories import CATEGORIES, infer_category


def fichiers() -> list[Path]:
    return [Path(p) for p in
            glob.glob("data/metas/*.json") + glob.glob("data/manual/*/metas.json")]


def main() -> None:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--apply", action="store_true",
        help="Write the new categories. Without it, only report.",
    )
    arguments = analyseur.parse_args()

    avant: collections.Counter = collections.Counter()
    apres: collections.Counter = collections.Counter()
    changes = 0
    for chemin in fichiers():
        metas = json.loads(chemin.read_text("utf-8"))
        for meta in metas:
            ancienne = meta["category"]
            nouvelle = infer_category(meta["title"], meta["description"])
            avant[ancienne] += 1
            apres[nouvelle] += 1
            if nouvelle != ancienne:
                changes += 1
                meta["category"] = nouvelle
        if arguments.apply:
            chemin.write_text(
                json.dumps(metas, indent=2, ensure_ascii=False), "utf-8"
            )

    total = sum(apres.values())
    print(f"{total} metas, {changes} recategorisees\n")
    print(f"{'categorie':16s} {'avant':>7s} {'apres':>7s}")
    for categorie in CATEGORIES:
        part = 100 * apres[categorie] / total if total else 0.0
        print(f"{categorie:16s} {avant.get(categorie, 0):7d} {apres[categorie]:7d}"
              f"  {part:5.1f}%")
    anciennes = sorted(set(avant) - set(CATEGORIES))
    if anciennes:
        print("\nSlugs disparus :", ", ".join(f"{a} ({avant[a]})" for a in anciennes))
    if not arguments.apply:
        print("\nSimulation. Relancer avec --apply pour ecrire.")


if __name__ == "__main__":
    main()
