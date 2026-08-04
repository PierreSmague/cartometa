from __future__ import annotations

import argparse
from pathlib import Path

from cartometa.build.dataset import discover_countries
from cartometa.build.geometry import DEFAULT_TOLERANCE
from cartometa.build.site import (
    FILE_COUNT_LIMIT,
    FILE_COUNT_WARNING,
    IMAGE_BASE,
    SITE_URL,
    build_site,
)


def main() -> None:
    analyseur = argparse.ArgumentParser(description="Construit le site public")
    analyseur.add_argument(
        "countries", nargs="*",
        help="Codes ISO à publier. Par défaut, tous ceux présents dans data/geo/.",
    )
    analyseur.add_argument("--data", type=Path, default=Path("data"))
    analyseur.add_argument("--out", type=Path, default=Path("dist"))
    analyseur.add_argument("--viewer", type=Path, default=Path("viewer"))
    analyseur.add_argument(
        "--simplify-tolerance", type=float, default=DEFAULT_TOLERANCE,
        help=f"Tolérance en degrés, plafonnée par emprise (défaut {DEFAULT_TOLERANCE}).",
    )
    analyseur.add_argument(
        "--skip-images", action="store_true",
        help="Saute l'encodage des images — pour itérer vite sur le code.",
    )
    analyseur.add_argument(
        "--image-base", default=IMAGE_BASE,
        help=(
            "Préfixe des URL d'images dans le manifeste. Passer une URL absolue "
            "(bucket R2 sur domaine personnalisé) déplace les images hors du "
            f"déploiement sans toucher au code. Défaut : {IMAGE_BASE}"
        ),
    )
    analyseur.add_argument(
        "--site-url", default=SITE_URL,
        help=(
            "Origine canonique inscrite dans les balises Open Graph, qui "
            "exigent des URL absolues sous peine d'aperçu vide au partage. "
            f"Défaut : {SITE_URL}"
        ),
    )
    analyseur.add_argument(
        "--google-key", default="",
        help=(
            "Clé Google Maps activant le second fond de carte. Sans elle, le "
            "sélecteur n'apparaît pas et le site n'appelle jamais Google. La "
            "passer ici plutôt que de la versionner : elle sera publique dans "
            "le manifeste de toute façon, mais n'a pas à rester dans "
            "l'historique git après une rotation. Restreins-la par référent "
            "HTTP côté console Google."
        ),
    )
    arguments = analyseur.parse_args()

    pays = [c.upper() for c in arguments.countries] or discover_countries(arguments.data)
    if not pays:
        raise SystemExit(
            f"Aucun pays à publier : {arguments.data / 'geo'} ne contient aucun "
            f".geojson.\nLance d'abord cartometa-extract puis cartometa-review."
        )

    resultat = build_site(
        arguments.data, arguments.out, arguments.viewer, pays,
        arguments.simplify_tolerance, arguments.skip_images,
        arguments.image_base, arguments.site_url, arguments.google_key,
    )

    detail = ", ".join(f"{p} {n}" for p, n in resultat["countries"].items())
    print(f"{resultat['metas']} métas publiées vers {resultat['output']} ({detail})")
    print(f"{resultat['files']} fichiers")

    if resultat["files"] >= FILE_COUNT_WARNING:
        print(
            f"\nAttention : {resultat['files']} fichiers, pour une limite de "
            f"{FILE_COUNT_LIMIT} par déploiement Cloudflare Pages.\n"
            f"Au plafond, c'est la publication qui échoue, pas le site en ligne.\n"
            f"Parade : déplacer img/ vers un bucket R2 et changer `image_base` "
            f"dans le manifeste."
        )
    if resultat["legacy_statuses"]:
        print(
            f"\nAttention : {resultat['legacy_statuses']} emprise(s) portent un "
            f"statut hérité (ni validé ni rejeté) et n'ont pas été publiées."
        )
    if resultat["orphans"]:
        details = ", ".join(f"{p}:{i}" for p, i in resultat["orphans"])
        print(
            f"\nAttention : {len(resultat['orphans'])} emprise(s) tracée(s) sans "
            f"texte de méta, non publiée(s) : {details}\n"
            f"Relancer cartometa-extract sur ces pays les republiera."
        )
    if arguments.skip_images:
        print(
            "\nAttention : --skip-images actif — ce dist/ ne contient aucune "
            "image. Le contrôle d'intégrité passe quand même (rien à vérifier "
            "sans clés thumb/full) : ne pas déployer ce dist/ tel quel."
        )


if __name__ == "__main__":
    main()
