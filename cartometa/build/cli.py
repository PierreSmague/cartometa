from __future__ import annotations

import argparse
import os
import re
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

# Repli de `--google-key`. Le sélecteur de fond de carte a déjà disparu du site
# une fois parce qu'un build lancé pour autre chose avait omis l'option : la clé
# ne vit que dans la ligne de commande, et `dist/` n'est pas versionné, donc
# rien ne rattrapait l'oubli. La poser une fois dans l'environnement rend
# n'importe quel build ultérieur complet par défaut.
GOOGLE_KEY_ENV = "CARTOMETA_GOOGLE_KEY"

# Forme documentée d'une clé de navigateur Google : « AIza » suivi de 35
# caractères. On la vérifie parce que rien d'autre ne le fait : le build
# recopie la valeur dans le manifeste sans la lire, et seul Google tranche —
# une fois le site en ligne, par un `InvalidKeyMapError` que le visiteur voit
# et que le build n'a jamais vu.
#
# Vécu : une empreinte hexadécimale de 40 caractères, prise pour une clé dans
# un fichier nommé `api_key.txt`, a été publiée telle quelle. Le build a
# réussi, annoncé un sélecteur de fond de carte, et le fond Google était mort
# en production. Un contrôle de forme coûte une ligne et aurait tout arrêté au
# bon moment.
FORME_CLE_GOOGLE = re.compile(r"^AIza[0-9A-Za-z_-]{35}$")


def verifier_cle_google(cle: str) -> None:
    """Refuse une valeur qui ne peut pas être une clé Google.

    Ne dit rien de sa validité — seul Google le sait — mais élimine la faute
    qui coûte le plus cher : publier autre chose qu'une clé.
    """
    if cle and not FORME_CLE_GOOGLE.fullmatch(cle):
        raise SystemExit(
            f"La clé Google fournie ne peut pas en être une : "
            f"{len(cle)} caractères, « AIza » + 35 attendus.\n"
            f"Publier cette valeur construirait un site annonçant un fond "
            f"Google que l'API refuserait (InvalidKeyMapError), sans que rien "
            f"ne le signale avant la mise en ligne.\n"
            f"Vérifie --google-key, ou {GOOGLE_KEY_ENV} si l'option est absente."
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
        "--google-key", default=os.environ.get(GOOGLE_KEY_ENV, ""),
        help=(
            "Clé Google Maps activant le second fond de carte. Sans elle, le "
            "sélecteur n'apparaît pas et le site n'appelle jamais Google. À "
            f"défaut, la variable d'environnement {GOOGLE_KEY_ENV} est lue : "
            "un build qui oublie l'option ne retire pas le sélecteur du site "
            "en silence. La passer ainsi plutôt que de la versionner : elle "
            "sera publique dans le manifeste de toute façon, mais n'a pas à "
            "rester dans l'historique git après une rotation. Restreins-la par "
            "référent HTTP côté console Google."
        ),
    )
    arguments = analyseur.parse_args()

    # Avant tout travail : douze minutes d'encodage d'images pour finir sur une
    # clé refusée seraient perdues, et surtout le dist/ produit serait bon à
    # jeter.
    verifier_cle_google(arguments.google_key)

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
    if not arguments.google_key:
        print(
            f"\nAttention : aucune clé Google — ce dist/ n'aura pas de sélecteur "
            f"de fond de carte, le visiteur restera sur OpenStreetMap.\n"
            f"Parade : passer --google-key, ou poser {GOOGLE_KEY_ENV} une fois "
            f"pour toutes dans l'environnement."
        )
    if arguments.skip_images:
        print(
            "\nAttention : --skip-images actif — ce dist/ ne contient aucune "
            "image. Le contrôle d'intégrité passe quand même (rien à vérifier "
            "sans clés thumb/full) : ne pas déployer ce dist/ tel quel."
        )


if __name__ == "__main__":
    main()
