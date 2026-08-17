from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from shapely.geometry import shape

from cartometa.build.geometry import DEFAULT_TOLERANCE, part_bboxes, simplify_geometry
from cartometa.extract.categories import CATEGORIES
from cartometa.models import STATUS_TRACED, STATUS_PROPOSED, STATUSES
from cartometa.review.store import CountryPaths, load_geo, load_metas

EXPORTABLE = (STATUS_TRACED,)

# Scope of a footprint, as the site offers it for filtering.
SCOPE_NATIONAL = "national"
SCOPE_REGIONAL = "regional"

# How hard the meta is to use in game, as the site offers it for filtering. There is
# deliberately no default: the field is optional, and a meta nobody has judged is
# published with `difficulty: None` rather than assumed to be a beginner's. The
# viewer then shows it no badge, and groups those under its "Not rated" pill.
DIFFICULTIES = ("Beginner", "Intermediate", "Pro")


def scope_de(pieces: list[dict]) -> str:
    """`national` if the footprint IS the whole country, `regional` otherwise.

    Derived from the drawing, not from the Plonk It `tier`. Both exist and agree
    96.8 % of the time (measured over the 1710 published footprints) but they do
    not say the same thing: `tier` says what Plonk It classified, the drawing
    says what the footprint actually covers on the map. It is that second
    question the filter asks — and above all, the drawing is *total*: every
    published footprint has one by construction, whereas `tier` is also
    `manual` for a hand-entered meta, a value that belongs to neither national
    nor regional and would leave those metas out of both filters.

    Strict equality, and not `"country" in kinds`: a footprint mixing `country`
    with another piece is a clipped or completed country, hence precisely no
    longer the whole country. No published footprint is in that case today (the
    two rules are equivalent there), but only equality stays correct if that
    changes.

    An empty list falls back to `regional`: no published footprint is in that
    case either, and this choice guarantees no meta can disappear from "All" —
    an invisible defect would be worse than a debatable classification.
    """
    kinds = {piece.get("kind") for piece in pieces}
    return SCOPE_NATIONAL if kinds == {"country"} else SCOPE_REGIONAL


@dataclass
class Dataset:
    """The publishable set, split up.

    `index` is global and light: it is enough to know, on click, which countries
    are worth downloading. `countries` carries the detail, one file per country.
    """

    index: list[list] = field(default_factory=list)
    countries: dict[str, dict] = field(default_factory=dict)
    legacy_statuses: int = 0
    # Drawn footprints whose meta text has vanished: (country, id). Counted so
    # the CLI can name them — data evaporating silently is worse than a build
    # that complains.
    orphans: list[tuple[str, str]] = field(default_factory=list)
    # Overrides naming an id the built country does not have: (country, id).
    # A typo in a hand-edited file must not leave a meta silently unfixed.
    unknown_overrides: list[tuple[str, str]] = field(default_factory=list)


def empreinte_geometrie(geometrie: dict) -> str:
    """Content fingerprint of a geometry, the key it is published under.

    Many metas share the same footprint — the national outline 19 times over in
    the Russian file alone, 25.9 MB of byte-identical duplicates out of the
    34.2 MB published (measured). Publishing each geometry once, under a key that
    depends only on its content, removes the duplication with nothing for the
    front end to recompute. Twelve hexdigits are plenty: the collision risk stays
    negligible far beyond a million footprints.
    """
    octets = json.dumps(geometrie, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(octets).hexdigest()[:12]


def discover_countries(data_dir: Path) -> list[str]:
    """Every country having a geometry file, in alphabetical order."""
    return sorted({p.stem.upper() for p in (data_dir / "geo").glob("*.geojson")})


def load_category_overrides(data_dir: Path) -> dict[str, dict[str, str]]:
    """Human corrections to the inferred categories, by country then meta id.

    Versioned, unlike `data/metas/`: a judgement stored only in a regenerable
    file is lost on the next `cartometa-extract`, which re-infers every category
    from the saved HTML.

    Keyed by country because meta ids are not globally unique — `yHR2` exists in
    both AT and ES, `Izqw` in CA and FR. A flat `{id: slug}` file would apply one
    correction to two unrelated metas.

    A category outside the taxonomy is fatal rather than a warning: it has no
    pill on the site, so the meta would show under "All" and be unreachable
    through every category filter. Half-invisible is worse than a failed build.
    """
    chemin = data_dir / "categories.json"
    if not chemin.exists():
        return {}
    overrides = json.loads(chemin.read_text("utf-8"))
    inconnues = sorted(
        f"{pays}/{identifiant} -> {categorie!r}"
        for pays, entrees in overrides.items()
        for identifiant, categorie in entrees.items()
        if categorie not in CATEGORIES
    )
    if inconnues:
        details = "\n".join(f"  - {i}" for i in inconnues)
        raise SystemExit(
            f"{chemin}: unknown category(ies):\n{details}\n"
            f"Expected one of {', '.join(CATEGORIES)}.\n"
            f"A category outside the list has no pill on the site: the meta "
            f"would be unreachable through every filter."
        )
    return overrides


def build_dataset(
    data_dir: Path,
    countries: list[str],
    tolerance: float = DEFAULT_TOLERANCE,
    outline_de: Callable[[str], dict | None] | None = None,
) -> Dataset:
    """Read the sources, simplify, split per country and build the index.

    `outline_de` provides, for a country code, the country silhouette as GeoJSON
    — or `None` when it is unavailable. Absent, no country file carries an
    `outline` key.
    """
    jeu = Dataset()
    overrides = load_category_overrides(data_dir)
    for pays in countries:
        chemins = CountryPaths(data_dir, pays)
        if not chemins.geo.exists():
            continue
        records = load_geo(chemins, resolve=True)
        features = [records[k].to_feature() for k in sorted(records)]
        jeu.legacy_statuses += sum(
            1 for f in features
            if f["properties"]["status"] not in STATUSES + (STATUS_PROPOSED,)
        )
        publiables = [
            f for f in features
            if f["properties"]["status"] in EXPORTABLE and f["geometry"]
        ]
        if not publiables:
            # Empty geojson, or everything `rejeté`: nothing to publish, and
            # that is not an error.
            continue
        metas = {m["id"]: m for m in load_metas(chemins)}
        if not metas:
            # The normal case on a fresh clone, not an anomaly: the 1710
            # footprints in `data/geo/` are versioned, their texts are not. So a
            # contributor lands here on their first argument-less
            # `cartometa-build`, right on the first country. The message has to
            # give them a way out — publish their single country — and not just
            # an order to regenerate 45 countries they do not have.
            raise SystemExit(
                f"{pays}: {len(publiables)} versioned footprint(s), but no meta "
                f"text.\n"
                f"The Plonk It texts are not versioned (data/metas/ is gitignored): "
                f"on a fresh clone that is the case for EVERY country, and it is not "
                f"an anomaly.\n"
                f"  - To preview only the country you are working on:\n"
                f"      uv run cartometa-build <COUNTRY_CODE>\n"
                f"  - To publish {pays} again: cartometa-extract regenerates it from "
                f"a Plonk It page saved by hand.\n"
                f"Hand-entered metas are expected in "
                f"{chemins.manual_metas}."
            )
        # Scoped to this country: an id the file names for another country is not
        # a typo, it simply is not being built now.
        corrections = overrides.get(pays, {})
        jeu.unknown_overrides.extend(
            (pays, identifiant) for identifiant in sorted(corrections)
            if identifiant not in metas
        )
        entree_pays = {"metas": {}, "geometries": {}}
        for feature in publiables:
            identifiant = feature["properties"]["id"]
            meta = metas.get(identifiant)
            if meta is None:
                jeu.orphans.append((pays, identifiant))
                continue
            # A missing field is the normal case, not an error; only a *filled* one
            # has to be one of the three known levels. Fatal rather than silently
            # dropped, for the same reason as an unknown category: the meta would be
            # published and unreachable through every difficulty pill.
            # `or None` so that an empty string — what an editing form leaves behind
            # when the level is cleared — means "not rated" and not "unknown level".
            difficulty = meta.get("difficulty") or None
            if difficulty is not None and difficulty not in DIFFICULTIES:
                raise SystemExit(
                    f"{pays}/{identifiant}: unknown difficulty {difficulty!r}.\n"
                    f"Expected one of {', '.join(DIFFICULTIES)}."
                )
            geometrie = simplify_geometry(feature["geometry"], tolerance)
            forme = shape(geometrie)
            # One index row per group of parts, not per footprint: the overall
            # bbox of a scattered multipolygon (Russia across ±180°, Norway all
            # the way to Bouvet) covers the planet and prefilters nothing any
            # more. Same id and same area on every row — the viewer dedupes the
            # ids, and sorting by area stays stable.
            surface = round(forme.area, 6)
            for min_lon, min_lat, max_lon, max_lat in part_bboxes(geometrie):
                jeu.index.append([
                    identifiant, pays,
                    round(min_lon, 4), round(min_lat, 4),
                    round(max_lon, 4), round(max_lat, 4),
                    surface,
                ])
            empreinte = empreinte_geometrie(geometrie)
            entree_pays["geometries"][empreinte] = geometrie
            entree_pays["metas"][identifiant] = {
                "geom": empreinte,
                "title": meta["title"],
                "description": meta["description"],
                "category": corrections.get(identifiant, meta["category"]),
                "difficulty": difficulty,
                "scope": scope_de(feature["properties"].get("pieces", [])),
                "source_url": meta["source_url"],
                "image_source": meta.get("image"),
                # RMRG only: the guide's region mini-map (SVG), baked into the
                # published images by the site build. None everywhere else.
                "overlay_source": meta.get("overlay"),
            }
        if entree_pays["geometries"] and outline_de is not None:
            # Country silhouette, background of the Anki cards' mini-map.
            # Injected rather than imported: the Natural Earth dataset comes over
            # the network, and neither this function nor its tests may touch it.
            contour = outline_de(pays)
            if contour is not None:
                entree_pays["outline"] = simplify_geometry(contour, tolerance)
        if entree_pays["geometries"]:
            jeu.countries[pays] = entree_pays
    # A Plonk It orphan is a regeneration lag, recoverable by re-running
    # cartometa-extract: we count it and the CLI names it. A `man-*` orphan is
    # something else: data/manual/ is versioned precisely because those entries
    # are irreplaceable, so its text exists nowhere any more. Publishing without
    # it would silently endorse the loss.
    perdues = [(pays, i) for pays, i in jeu.orphans if i.startswith("man-")]
    if perdues:
        details = "\n".join(f"  - {pays} : {i}" for pays, i in perdues)
        raise SystemExit(
            f"{len(perdues)} manual footprint(s) with no meta text:\n{details}\n"
            f"The text of a manual meta lives in data/manual/<CC>/metas.json and is "
            f"versioned: if it is missing, it was deleted or renamed. Restore it "
            f"from git, or remove the footprint from the geojson if the deletion "
            f"was intended."
        )
    # Sorted by increasing area: the viewer shows from most specific to most
    # general without having to sort anything itself.
    jeu.index.sort(key=lambda entree: entree[6])
    return jeu
