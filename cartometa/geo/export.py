from __future__ import annotations
import argparse
import json
from pathlib import Path

from shapely.geometry import shape

from cartometa.models import STATUS_TRACED
from cartometa.review.store import CountryPaths, load_metas

EXPORTABLE = (STATUS_TRACED,)


def discover_countries(data_dir: Path) -> list[str]:
    """Tous les pays ayant des géométries construites, par ordre alphabétique.

    Permet d'exporter sans nommer les pays : le viewer affiche par défaut
    tout ce qui a été traité, et un nouveau pays y entre dès qu'une de ses
    métas a été tracée, sans changer la commande d'export.
    """
    return sorted({p.stem.upper() for p in (data_dir / "geo").glob("*.geojson")})


def export_viewer(data_dir: Path, out_dir: Path, countries: list[str]) -> dict:
    """Exporte les données du viewer public.

    Seules les métas tracées à la main sortent : le statut `rejeté` et
    l'absence de décision ne publient rien. Les deux sources de métas —
    import Plonk It et saisie manuelle — sont fusionnées à la lecture.
    """
    index, geometries = [], {}
    by_country: dict[str, int] = {}
    for country in countries:
        paths = CountryPaths(data_dir, country)
        if not paths.geo.exists():
            continue
        geo = json.loads(paths.geo.read_text("utf-8"))
        exportable = [
            feature for feature in geo["features"]
            if feature["properties"]["status"] in EXPORTABLE and feature["geometry"]
        ]
        if not exportable:
            # Rien à publier pour ce pays : géojson vide ou tout en `rejeté`.
            # Un clone frais laisse 21 .geojson vides et suivis — ce n'est
            # pas une erreur, juste rien à faire ici.
            continue
        metas = {m["id"]: m for m in load_metas(paths)}
        if not metas:
            raise SystemExit(
                f"{country}: géométries présentes mais aucune méta.\n"
                f"Les textes Plonk It ne sont pas versionnés — régénère-les avec "
                f"cartometa-extract, ou vérifie {paths.manual_metas}."
            )
        for feature in exportable:
            props = feature["properties"]
            meta = metas.get(props["id"])
            if meta is None:
                continue
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
    args = parser.parse_args()
    countries = [c.upper() for c in args.countries] or discover_countries(args.data)
    if not countries:
        raise SystemExit(
            f"Aucun pays à exporter : {args.data / 'geo'} ne contient aucun .geojson.\n"
            f"Lance d'abord cartometa-extract puis cartometa-review."
        )
    result = export_viewer(args.data, args.out, countries)
    detail = ", ".join(f"{c} {n}" for c, n in result["by_country"].items())
    print(f"{result['exported']} métas exportées vers {result['output']} ({detail})")


if __name__ == "__main__":
    main()
