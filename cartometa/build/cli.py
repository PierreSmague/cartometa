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

# Fallback for `--google-key`. The base map switch already vanished from the
# site once because a build launched for something else had omitted the option:
# the key only lives on the command line, and `dist/` is not versioned, so
# nothing caught the omission. Setting it once in the environment makes any
# later build complete by default.
GOOGLE_KEY_ENV = "CARTOMETA_GOOGLE_KEY"

# Documented shape of a Google browser key: "AIza" followed by 35 characters.
# We check it because nothing else does: the build copies the value into the
# manifest without reading it, and only Google decides — once the site is live,
# through an `InvalidKeyMapError` the visitor sees and the build never saw.
#
# From experience: a 40-character hex fingerprint, mistaken for a key in a file
# named `api_key.txt`, was published as-is. The build succeeded, announced a
# base map switch, and the Google base map was dead in production. A shape
# check costs one line and would have stopped everything at the right moment.
FORME_CLE_GOOGLE = re.compile(r"^AIza[0-9A-Za-z_-]{35}$")


def verifier_cle_google(cle: str) -> None:
    """Reject a value that cannot possibly be a Google key.

    Says nothing about its validity — only Google knows that — but rules out
    the costliest mistake: publishing something that is not a key at all.
    """
    if cle and not FORME_CLE_GOOGLE.fullmatch(cle):
        raise SystemExit(
            f"The Google key given cannot possibly be one: "
            f"{len(cle)} characters, \"AIza\" + 35 expected.\n"
            f"Publishing this value would build a site advertising a Google base "
            f"map that the API would refuse (InvalidKeyMapError), with nothing to "
            f"flag it before going live.\n"
            f"Check --google-key, or {GOOGLE_KEY_ENV} if the option is absent."
        )


def main() -> None:
    analyseur = argparse.ArgumentParser(description="Builds the public site")
    analyseur.add_argument(
        "countries", nargs="*",
        help="ISO codes to publish. By default, every code found in data/geo/.",
    )
    analyseur.add_argument("--data", type=Path, default=Path("data"))
    analyseur.add_argument("--out", type=Path, default=Path("dist"))
    analyseur.add_argument("--viewer", type=Path, default=Path("viewer"))
    analyseur.add_argument(
        "--simplify-tolerance", type=float, default=DEFAULT_TOLERANCE,
        help=f"Tolerance in degrees, capped per footprint (default {DEFAULT_TOLERANCE}).",
    )
    analyseur.add_argument(
        "--skip-images", action="store_true",
        help="Skips image encoding - to iterate fast on the code.",
    )
    analyseur.add_argument(
        "--image-base", default=IMAGE_BASE,
        help=(
            "Prefix of the image URLs in the manifest. Passing an absolute URL "
            "(an R2 bucket on a custom domain) moves the images out of the "
            f"deployment without touching the code. Default: {IMAGE_BASE}"
        ),
    )
    analyseur.add_argument(
        "--site-url", default=SITE_URL,
        help=(
            "Canonical origin written into the Open Graph tags, which require "
            "absolute URLs on pain of an empty preview when shared. "
            f"Default: {SITE_URL}"
        ),
    )
    analyseur.add_argument(
        "--google-key", default=os.environ.get(GOOGLE_KEY_ENV, ""),
        help=(
            "Google Maps key enabling the second base map. Without it, the "
            "switch does not appear and the site never calls Google. Failing "
            f"the option, the {GOOGLE_KEY_ENV} environment variable is read: "
            "a build that forgets the option does not silently remove the "
            "switch from the site. Prefer this over versioning the key: it "
            "will be public in the manifest anyway, but it does not need to "
            "stay in git history after a rotation. Restrict it by HTTP "
            "referrer in the Google console."
        ),
    )
    arguments = analyseur.parse_args()

    # Before any work: twelve minutes of image encoding ending on a rejected
    # key would be wasted, and above all the resulting dist/ would be fit for
    # the bin.
    verifier_cle_google(arguments.google_key)

    pays = [c.upper() for c in arguments.countries] or discover_countries(arguments.data)
    if not pays:
        raise SystemExit(
            f"No country to publish: {arguments.data / 'geo'} contains no "
            f".geojson.\nRun cartometa-extract then cartometa-review first."
        )

    resultat = build_site(
        arguments.data, arguments.out, arguments.viewer, pays,
        arguments.simplify_tolerance, arguments.skip_images,
        arguments.image_base, arguments.site_url, arguments.google_key,
    )

    detail = ", ".join(f"{p} {n}" for p, n in resultat["countries"].items())
    print(f"{resultat['metas']} metas published to {resultat['output']} ({detail})")
    print(f"{resultat['files']} files")

    if resultat["files"] >= FILE_COUNT_WARNING:
        print(
            f"\nWarning: {resultat['files']} files, against a limit of "
            f"{FILE_COUNT_LIMIT} per Cloudflare Pages deployment.\n"
            f"At the cap it is the publication that fails, not the live site.\n"
            f"Workaround: move img/ to an R2 bucket and change `image_base` "
            f"in the manifest."
        )
    if resultat["legacy_statuses"]:
        print(
            f"\nWarning: {resultat['legacy_statuses']} footprint(s) carry a legacy "
            f"status (neither validé nor rejeté) and were not published."
        )
    if resultat["orphans"]:
        details = ", ".join(f"{p}:{i}" for p, i in resultat["orphans"])
        print(
            f"\nWarning: {len(resultat['orphans'])} drawn footprint(s) with no meta "
            f"text, not published: {details}\n"
            f"Re-running cartometa-extract on those countries will publish them."
        )
    if not arguments.google_key:
        print(
            f"\nWarning: no Google key - this dist/ will have no base map switch, "
            f"and the visitor will stay on OpenStreetMap.\n"
            f"Workaround: pass --google-key, or set {GOOGLE_KEY_ENV} once and for "
            f"all in the environment."
        )
    if arguments.skip_images:
        print(
            "\nWarning: --skip-images is on - this dist/ contains no image. The "
            "integrity check passes all the same (nothing to check without "
            "thumb/full keys): do not deploy this dist/ as it stands."
        )


if __name__ == "__main__":
    main()
