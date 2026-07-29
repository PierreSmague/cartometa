from __future__ import annotations
import argparse
import json
from pathlib import Path

from shapely.geometry import shape

EXPORTABLE = ("validé", "corrigé")


def discover_countries(data_dir: Path) -> list[str]:
    """Tous les pays ayant des géométries construites, par ordre alphabétique.

    Permet d'exporter sans nommer les pays : le viewer affiche par défaut
    tout ce qui a été traité, et un nouveau pays y entre dès que
    ``cartometa-geo`` a tourné, sans changer la commande d'export.
    """
    return sorted({p.stem.upper() for p in (data_dir / "geo").glob("*.geojson")})


def export_viewer(
    data_dir: Path, out_dir: Path, countries: list[str], include_auto: bool = False
) -> dict:
    """Exporte les données du viewer public.

    Par défaut, seules les métas de statut ``validé`` ou ``corrigé`` sont
    exportées : la revue humaine (Task 11) est la porte d'entrée vers la
    publication. ``include_auto=True`` lève exceptionnellement cette porte
    pour inclure aussi les métas encore au statut ``auto`` — utile pour
    faire fonctionner et vérifier le viewer avant que la revue ait eu lieu
    (voir Step 5 du brief Task 12). Ce n'est pas un mode de publication :
    l'appelant reste responsable de ne pas diffuser des données non
    validées, et le nombre de métas non revues incluses est rapporté dans
    le résultat pour qu'un tel usage ne passe jamais inaperçu.
    """
    exportable_statuses = EXPORTABLE + ("auto",) if include_auto else EXPORTABLE
    index, geometries = [], {}
    unreviewed_included = 0
    by_country: dict[str, int] = {}
    for country in countries:
        metas_path = data_dir / "metas" / f"{country}.json"
        if not metas_path.exists():
            raise SystemExit(
                f"{country}: géométries présentes mais {metas_path} est absent.\n"
                f"Les textes Plonk It ne sont pas versionnés — régénère-les avec "
                f"cartometa-extract."
            )
        metas = {m["id"]: m for m in json.loads(metas_path.read_text("utf-8"))}
        geo = json.loads((data_dir / "geo" / f"{country}.geojson").read_text("utf-8"))
        for feature in geo["features"]:
            props = feature["properties"]
            if props["status"] not in exportable_statuses or not feature["geometry"]:
                continue
            meta = metas.get(props["id"])
            if meta is None:
                continue
            if props["status"] not in EXPORTABLE:
                unreviewed_included += 1
            geom = shape(feature["geometry"])
            index.append({
                "id": props["id"], "country": country, "tier": meta["tier"],
                "title": meta["title"], "description": meta["description"],
                "category": meta["category"], "image": meta.get("image"),
                "source_url": meta["source_url"],
                "bbox": [round(v, 4) for v in geom.bounds],
                "area": round(geom.area, 6),
            })
            geometries[props["id"]] = feature["geometry"]
            by_country[country] = by_country.get(country, 0) + 1

    index.sort(key=lambda entry: entry["area"])
    target = out_dir / "data"
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.json").write_text(json.dumps(index, ensure_ascii=False), "utf-8")
    (target / "geometries.json").write_text(json.dumps(geometries, ensure_ascii=False), "utf-8")
    return {
        "exported": len(index),
        "countries": countries,
        "by_country": {c: by_country.get(c, 0) for c in countries},
        "output": str(target),
        "unreviewed_included": unreviewed_included,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporte les données du viewer")
    parser.add_argument(
        "countries",
        nargs="*",
        help="Codes ISO à exporter. Par défaut, tous les pays présents dans data/geo/.",
    )
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("viewer"))
    parser.add_argument(
        "--include-auto",
        action="store_true",
        help=(
            "Inclut aussi les métas de statut 'auto' (non encore revues), en plus "
            "de 'validé'/'corrigé'. Désactivé par défaut : ne pas utiliser pour "
            "une publication réelle, seulement pour faire fonctionner et vérifier "
            "le viewer avant la revue humaine."
        ),
    )
    args = parser.parse_args()
    countries = [c.upper() for c in args.countries] or discover_countries(args.data)
    if not countries:
        raise SystemExit(
            f"Aucun pays à exporter : {args.data / 'geo'} ne contient aucun .geojson.\n"
            f"Lance d'abord cartometa-extract puis cartometa-geo."
        )
    result = export_viewer(args.data, args.out, countries, include_auto=args.include_auto)
    detail = ", ".join(f"{c} {n}" for c, n in result["by_country"].items())
    print(f"{result['exported']} métas exportées vers {result['output']} ({detail})")
    if result["unreviewed_included"]:
        print(
            f"  ATTENTION: {result['unreviewed_included']} méta(s) non revue(s) "
            f"(statut 'auto') incluse(s) via --include-auto — à ne pas publier telles quelles."
        )


if __name__ == "__main__":
    main()
