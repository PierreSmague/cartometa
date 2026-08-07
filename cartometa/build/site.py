from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple

from shapely.geometry import mapping

from cartometa.build.assets import write_hashed
from cartometa.build.dataset import build_dataset
from cartometa.build.geometry import DEFAULT_TOLERANCE
from cartometa.build.image_cache import ImageCache
from cartometa.build.images import MissingImageError, render_image_pair
from cartometa.geo.reference import country_geometry

# Cloudflare Pages refuses a deployment beyond 20,000 files. We warn well ahead
# of that so the wall is seen coming months in advance: the workaround (moving
# the images to R2) takes an hour or two, not five minutes of panic.
FILE_COUNT_LIMIT = 20_000
FILE_COUNT_WARNING = 15_000

IMAGE_BASE = "img/"

# Assets copied from `viewer/` under a fingerprinted name, and the placeholder
# they replace in the HTML templates. Adding them here is enough: the copy loop,
# the substitution and the integrity check all derive from this list.
ACTIFS_STATIQUES = (
    ("style.css", "__CSS__"),
    ("app.js", "__JS__"),
    ("anki.js", "__ANKI_JS__"),
    ("favicon.svg", "__ICON_SVG__"),
    ("favicon.png", "__ICON_PNG__"),
    ("og.png", "__OG_IMAGE__"),
    # Leaflet plugin for the Google base map. Published and fingerprinted like
    # the others, but deliberately absent from the templates: the front end
    # fetches it through the manifest, and only if the visitor asks for that base
    # map. A `<script>` tag would have everyone download it, including the vast
    # majority who will never leave OpenStreetMap.
    ("googleMutant.js", "__GOOGLE_MUTANT__"),
)

# Canonical origin of the site, substituted for `__SITE_URL__` in the templates.
# Open Graph tags require absolute URLs: a relative path is ignored by most
# preview crawlers, and the thumbnail stays empty. The site currently answers on
# three origins (the domain, its `www`, and `cartometa.pages.dev`) — hence an
# explicit setting rather than a domain hard-coded into a template served from
# all three.
SITE_URL = "https://cartometa.com"

# Fingerprinted files live under `data/h/`, never directly under `data/` where
# `manifest.json` sits. A `/data/*` pattern would also cover the manifest, and
# nothing in the repository settles which of the two regimes (no-cache or
# immutable) Cloudflare would then apply: an overlap whose outcome cannot be
# verified would silently freeze the site on a stale manifest. We remove the
# question by making sure no pattern can ever match both paths at once.
#
# The HTML pages are declared under BOTH their forms. Cloudflare Pages serves
# clean URLs: it redirects `/index.html` to `/` and `/licence.html` to
# `/licence`. Verified in production, a rule written on the file name alone
# therefore only applies to an address nobody visits, and the real page falls
# back to the host's default. That default happens to be equivalent
# (`max-age=0, must-revalidate`), but depending on a third party's default for a
# guarantee you believe you wrote is exactly the trap already hit on the manifest.
#
# `/404.html` is declared under its file name only, and that is accepted:
# Cloudflare serves that page under whatever unknown address was requested, which
# cannot be enumerated. The catch-all `/*` pattern that would cover them all would
# also cover `/data/h/*` and `/*.js` — landing us right back in the overlap
# described above, only worse. So we prefer to promise nothing for those addresses
# rather than put the immutable cache at risk.
HEADERS = """\
/
  Cache-Control: no-cache
/index.html
  Cache-Control: no-cache
/licence
  Cache-Control: no-cache
/licence.html
  Cache-Control: no-cache
/404
  Cache-Control: no-cache
/404.html
  Cache-Control: no-cache
/data/manifest.json
  Cache-Control: no-cache
/data/h/*
  Cache-Control: public, max-age=31536000, immutable
/img/*
  Cache-Control: public, max-age=31536000, immutable
/*.js
  Cache-Control: public, max-age=31536000, immutable
/*.css
  Cache-Control: public, max-age=31536000, immutable
/*.svg
  Cache-Control: public, max-age=31536000, immutable
/*.png
  Cache-Control: public, max-age=31536000, immutable
"""


def _dumps(payload) -> bytes:
    """Compact, deterministic JSON: no whitespace, sorted keys.

    Sorting the keys is what makes the fingerprint reproducible from one build to
    the next — without it, insertion order alone would be enough to renew the file
    name and flush the visitors' cache for nothing.
    """
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


class ResultatVerification(NamedTuple):
    """Result of `verifier_integrite`: what is missing, and whether the images
    were merely set aside because they live elsewhere."""

    manquants: list[str]
    images_ignorees: bool


def _base_est_absolue(image_base: str) -> bool:
    """True when `image_base` denotes external storage rather than a path under
    `out_dir`: a scheme (`https://`, `s3://`...) or a protocol-relative prefix
    (`//cdn.example/...`). In both cases the images are no longer written where the
    manifest looks for them — checking them under `out_dir` would produce thousands
    of false positives.
    """
    a_un_schema = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", image_base)
    return bool(a_un_schema) or image_base.startswith("//")


def verifier_integrite(out_dir: Path, manifeste: dict) -> ResultatVerification:
    """Check that every path referenced by the manifest really exists on disk:
    the global index, each country file, and — except when `image_base` points to
    external storage — the thumbnail (`thumb`) and the full-size image (`full`) of
    each meta. Also checks the page itself: `index.html`, `_headers`, and every
    fingerprinted asset declared in `ACTIFS_STATIQUES` (script, stylesheet,
    favicons). `licence.html` stays optional: its presence is not required here.

    A pure function, free of side effects: it only inspects `out_dir` and the
    already-written `manifeste`, which makes it testable without building a
    complete site and replayable after the fact on an already deployed `dist/` —
    including on a manifest one did not produce oneself, and which may therefore be
    incomplete or truncated: a missing file, an unreadable one, or a missing key are
    each reported, never allowed to surface as an exception.

    Without the page part, the incident that motivated this check (a concurrent
    `rmtree` emptying `dist/` mid-write) could still produce a build that declares
    itself successful while the deployed page has neither script nor stylesheet — a
    site that renders blank, without a single error at build time.
    """
    manquants: list[str] = []

    if not (out_dir / "index.html").exists():
        manquants.append(str(out_dir / "index.html"))
    if not (out_dir / "_headers").exists():
        manquants.append(str(out_dir / "_headers"))
    # The exact name is fingerprinted (content hash) and is not carried in the
    # manifest: so we check the pattern rather than a precise name, which works
    # just as well right after this build as replayed later on a `dist/` produced
    # elsewhere.
    # Derived from ACTIFS_STATIQUES: adding an asset over there is enough for it to
    # be checked here, with no risk of forgetting one of the two lists.
    for fichier, _ in ACTIFS_STATIQUES:
        tige, suffixe = Path(fichier).stem, Path(fichier).suffix
        motif = f"{tige}.*{suffixe}"
        if not any(out_dir.glob(motif)):
            manquants.append(f"{out_dir / motif} (no fingerprinted file found)")

    index_rel = manifeste.get("index")
    if index_rel is None:
        manquants.append("manifest: 'index' key absent")
    else:
        chemin_index = out_dir / "data" / index_rel
        if not chemin_index.exists():
            manquants.append(str(chemin_index))

    image_base = manifeste.get("image_base", IMAGE_BASE)
    images_ignorees = _base_est_absolue(image_base)

    for code, entree in manifeste.get("countries", {}).items():
        fichier_rel = entree.get("file")
        if fichier_rel is None:
            manquants.append(f"manifest: country '{code}' has no 'file' key")
            continue
        chemin_pays = out_dir / "data" / fichier_rel
        if not chemin_pays.exists():
            manquants.append(str(chemin_pays))
            continue  # no file to read the metas out of

        if images_ignorees:
            continue

        try:
            contenu = json.loads(chemin_pays.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as erreur:
            # A full disk truncates a file that still exists: it passes the
            # .exists() test above but its JSON is invalid. That is a distinct
            # diagnosis from an absence, not an exception to let through — this
            # function has to stay the reliable source even on the degraded case
            # that motivated it.
            manquants.append(f"{chemin_pays} (unreadable: {erreur})")
            continue

        for meta in contenu.get("metas", {}).values():
            for cle in ("thumb", "full"):
                relatif = meta.get(cle)
                if relatif is None:
                    continue
                chemin_image = out_dir / image_base / relatif
                if not chemin_image.exists():
                    manquants.append(str(chemin_image))

    return ResultatVerification(manquants, images_ignorees)


def _fabrique_contours(data_dir: Path) -> Callable[[str], dict | None]:
    """Provider of country silhouettes for `build_dataset`.

    Three outcomes, never a build failure: the silhouette (the normal case), None
    for a country outside Natural Earth (KeyError), None for every country from the
    first dataset access failure onwards (OSError: offline without a cache, disk).
    The failure is remembered so as not to retry — and complain — once per country.
    """
    panne = False

    def contour_de(pays: str) -> dict | None:
        nonlocal panne
        if panne:
            return None
        try:
            return mapping(country_geometry(pays, data_dir / "cache"))
        except KeyError:
            print(f"  ! {pays} absent from Natural Earth: mini-map without background")
            return None
        except OSError as erreur:
            panne = True
            print(f"  ! Natural Earth unavailable ({erreur}): "
                  f"mini-maps without a country background")
            return None

    return contour_de


def build_site(
    data_dir: Path,
    out_dir: Path,
    viewer_dir: Path,
    countries: list[str],
    tolerance: float = DEFAULT_TOLERANCE,
    skip_images: bool = False,
    image_base: str = IMAGE_BASE,
    site_url: str = SITE_URL,
    google_key: str = "",
) -> dict:
    """Produce a complete, self-contained `dist/`.

    Clean slate on every call: a country removed from the sources has to disappear
    from the site, not survive as an orphan file the deployment would republish.
    """
    jeu = build_dataset(
        data_dir, countries, tolerance, outline_de=_fabrique_contours(data_dir)
    )

    # Safety rail: `--out` pointing by mistake at `viewer/` (the old default of the
    # binary removed by this very migration) or at `data/` (a simple swap with
    # `--data`) would erase the source viewer or months of irreplaceable manual
    # drawing respectively. We only wipe what already looks like an output of this
    # same build.
    if (
        out_dir.exists()
        and any(out_dir.iterdir())
        and not (out_dir / "_headers").exists()
    ):
        raise SystemExit(
            f"{out_dir} is not empty and does not look like a build output "
            f"(no _headers) - refusing to erase it."
        )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # Outside `out_dir`, which has just been wiped: the cache has to outlive the
    # build it speeds up. `data/cache/` is already gitignored.
    cache_images = ImageCache(data_dir / "cache" / "images")

    manifeste_pays: dict[str, dict] = {}
    for pays, contenu in sorted(jeu.countries.items()):
        for identifiant, meta in contenu["metas"].items():
            source = meta.pop("image_source", None)
            # Popped BEFORE the skip: neither working path may ever reach the
            # published JSON, images or not.
            trace = meta.pop("overlay_source", None)
            if skip_images or not source:
                continue
            try:
                # RMRG ids are paths ("agriculture/dung-piles"): used raw as a
                # stem they would nest directories under img/<CC>/. write_hashed
                # expects a NAME, so the stem is flattened — the id itself keeps
                # its slashes everywhere else.
                noms = render_image_pair(
                    Path(source), out_dir / IMAGE_BASE / pays,
                    identifiant.replace("/", "-"), cache_images,
                    overlay=Path(trace) if trace else None,
                )
            except MissingImageError as erreur:
                raise SystemExit(
                    f"{pays}/{identifiant}: {erreur}\n"
                    f"The source pages are not versioned: check input/."
                ) from erreur
            meta["thumb"] = f"{pays}/{noms['thumb']}"
            meta["full"] = f"{pays}/{noms['full']}"
        nom = write_hashed(out_dir / "data" / "h" / "c", pays, ".json", _dumps(contenu))
        # `metas`, not `geometries`: since fingerprint deduplication, several metas
        # can share one geometry — the count shown is the count of metas.
        manifeste_pays[pays] = {
            "file": f"h/c/{nom}", "count": len(contenu["metas"])
        }

    nom_index = "h/" + write_hashed(
        out_dir / "data" / "h", "index", ".json", _dumps(jeu.index)
    )

    noms_statiques = {}
    for fichier, marqueur in ACTIFS_STATIQUES:
        chemin = viewer_dir / fichier
        octets = chemin.read_bytes()
        tige, suffixe = chemin.stem, chemin.suffix
        noms_statiques[marqueur] = write_hashed(out_dir, tige, suffixe, octets)

    for page in ("index.html", "licence.html", "404.html"):
        source = viewer_dir / page
        if not source.exists():
            continue
        texte = source.read_text("utf-8")
        for marqueur, nom in noms_statiques.items():
            texte = texte.replace(marqueur, nom)
        # After the fingerprinted names: `__SITE_URL__/__OG_IMAGE__` must first
        # become `__SITE_URL__/og.<hash>.png`, then the origin is substituted.
        texte = texte.replace("__SITE_URL__", site_url.rstrip("/"))
        (out_dir / page).write_text(texte, "utf-8")

    (out_dir / "_headers").write_text(HEADERS, "utf-8")

    # The number of metas, not of index rows: since per-part bboxes, a scattered
    # footprint takes up several rows.
    nombre_metas = sum(len(c["metas"]) for c in jeu.countries.values())

    manifeste = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta_count": nombre_metas,
        # Read by the front end, never hard-coded: moving the images over to an R2
        # bucket is done by changing this single value.
        "image_base": image_base,
        "index": nom_index,
        # Fingerprinted name of the plugin, which the front end loads on demand.
        "google_mutant": noms_statiques["__GOOGLE_MUTANT__"],
        "countries": manifeste_pays,
    }
    # Absent rather than empty when no key is supplied: the front end only shows
    # the base map switch if the key exists. A contributor builds without a key and
    # gets a whole site, simply without the Google base map.
    #
    # The key travels through the build rather than through the repository. It will
    # end up readable in this manifest anyway — a browser key is public by nature,
    # what protects it is the referrer restriction, not secrecy. But it has no
    # reason to enter git history, where it would linger after any rotation.
    if google_key:
        manifeste["google_key"] = google_key
    (out_dir / "data" / "manifest.json").write_text(
        json.dumps(manifeste, ensure_ascii=False), "utf-8"
    )

    # Final integrity check: a truncated `dist/` (full disk, interrupted build,
    # concurrent write that overwrote it halfway through) must never declare itself
    # complete. Lived through for real once — a surviving build reported 1710 metas
    # across 45 countries while only 11 country files still existed on disk.
    verification = verifier_integrite(out_dir, manifeste)
    if verification.manquants:
        n = len(verification.manquants)
        apercu = "\n".join(f"  - {chemin}" for chemin in verification.manquants[:5])
        raise SystemExit(
            f"Corrupted build: {n} path(s) referenced by the manifest are absent "
            f"from {out_dir} - this dist/ must not be deployed.\n"
            f"{apercu}"
        )

    fichiers = sum(1 for p in out_dir.rglob("*") if p.is_file())
    return {
        "metas": nombre_metas,
        "countries": {p: e["count"] for p, e in manifeste_pays.items()},
        "files": fichiers,
        "legacy_statuses": jeu.legacy_statuses,
        "orphans": jeu.orphans,
        "unknown_overrides": jeu.unknown_overrides,
        "output": str(out_dir),
    }
