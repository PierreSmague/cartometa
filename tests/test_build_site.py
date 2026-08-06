import fnmatch
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from cartometa.build.site import (
    FILE_COUNT_LIMIT,
    FILE_COUNT_WARNING,
    _dumps,
    build_site,
    verifier_integrite,
)


def _carre(x: float, y: float, cote: float) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [x, y], [x + cote, y], [x + cote, y + cote], [x, y + cote], [x, y],
    ]]}


@pytest.fixture
def projet(tmp_path, monkeypatch):
    """A minimal but complete project: data, source images, templates.

    Metas store their image path relative to the project root (a convention already in
    place in `cartometa.extract` and `cartometa.review`), so we chdir into `tmp_path` so
    that this root is the throwaway project's and not the real repository's.
    """
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    (data / "metas").mkdir(parents=True)
    (data / "geo").mkdir(parents=True)
    images = tmp_path / "input"
    images.mkdir()
    Image.new("RGB", (1000, 500), (10, 20, 30)).save(images / "pl1.png")
    (data / "metas" / "PL.json").write_text(json.dumps([{
        "id": "pl1", "tier": "regional", "title": "titre", "description": "desc",
        "category": "autre", "image": "input/pl1.png",
        "source_url": "https://www.plonkit.net/poland#pl1",
    }]), "utf-8")
    (data / "geo" / "PL.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "pl1", "status": "validé", "pieces": []},
                      "geometry": _carre(14.0, 49.0, 5.0)}],
    }), "utf-8")

    viewer = tmp_path / "viewer"
    viewer.mkdir()
    (viewer / "index.html").write_text(
        "<!doctype html><head>__ICON_SVG__ __ICON_PNG__ __SITE_URL__/__OG_IMAGE__ Find all relevant metas</head>"
        "<body>__CSS__ __JS__</body>", "utf-8"
    )
    (viewer / "licence.html").write_text(
        "<!doctype html><head>__ICON_SVG__ __SITE_URL__/licence</head><body>__CSS__</body>", "utf-8"
    )
    (viewer / "404.html").write_text(
        "<!doctype html><head><link href='/__CSS__'></head>"
        "<body><a href='/'>retour</a></body>", "utf-8"
    )
    (viewer / "style.css").write_text("body{margin:0}", "utf-8")
    (viewer / "app.js").write_text("console.log('x')", "utf-8")
    (viewer / "anki.js").write_text("/* anki */", "utf-8")
    # Vendored Leaflet plugin, loaded on demand by the front end: it is referenced by
    # no template, only by the manifest.
    (viewer / "googleMutant.js").write_text("/* greffon */", "utf-8")
    (viewer / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", "utf-8")
    Image.new("RGBA", (32, 32), (193, 40, 58, 255)).save(viewer / "favicon.png")
    Image.new("RGB", (1200, 630), (240, 240, 235)).save(viewer / "og.png")
    return tmp_path


@pytest.fixture(autouse=True)
def sans_natural_earth(monkeypatch):
    """This file's default: Natural Earth unreachable, hence never any network.

    `build_site` wires `country_geometry` into `build_dataset` to publish the country
    silhouettes, and that dataset downloads (25 MB) as soon as the cache is missing —
    which is the case for every `tmp_path` in this file. So the default is the access
    failure, precisely what `_fabrique_contours` has to absorb: the tests that want a
    silhouette provide one themselves.
    """
    def _hors_ligne(code, cache_dir):
        raise OSError("dataset not downloaded (test fixture)")

    monkeypatch.setattr("cartometa.build.site.country_geometry", _hors_ligne)


def _manifeste(dist: Path) -> dict:
    return json.loads((dist / "data" / "manifest.json").read_text("utf-8"))


def _fichier_pays(dist: Path, code: str) -> dict:
    relatif = _manifeste(dist)["countries"][code]["file"]
    return json.loads((dist / "data" / relatif).read_text("utf-8"))


def _regles(headers: str) -> list[tuple[str, dict[str, str]]]:
    """Split a `_headers` file into (pattern, headers), in order.

    An unindented line opens a new pattern; the indented lines that follow are its
    headers.
    """
    regles: list[tuple[str, dict[str, str]]] = []
    for ligne in headers.splitlines():
        if not ligne.strip():
            continue
        if not ligne[0].isspace():
            regles.append((ligne.strip(), {}))
        else:
            cle, _, valeur = ligne.strip().partition(":")
            regles[-1][1][cle.strip()] = valeur.strip()
    return regles


def test_the_result_exposes_orphans_so_the_cli_can_name_them(projet):
    """`build_dataset` counts the footprints whose text has vanished; if `build_site`'s
    result does not pass them on, the CLI has nothing to show and the orphan stays
    invisible."""
    geo_path = projet / "data" / "geo" / "PL.geojson"
    geo = json.loads(geo_path.read_text("utf-8"))
    geo["features"].append({
        "type": "Feature",
        "properties": {"id": "pl-sans-texte", "status": "validé", "pieces": []},
        "geometry": _carre(15.0, 50.0, 1.0),
    })
    geo_path.write_text(json.dumps(geo), "utf-8")

    resultat = build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    assert resultat["orphans"] == [("PL", "pl-sans-texte")]


def test_the_meta_count_does_not_count_duplicate_index_rows(projet):
    """Since per-part bboxes, a scattered footprint takes up several index rows: the
    count shown (manifest and CLI) has to stay the count of metas, not of rows."""
    geo_path = projet / "data" / "geo" / "PL.geojson"
    geo = json.loads(geo_path.read_text("utf-8"))
    geo["features"][0]["geometry"] = {"type": "MultiPolygon", "coordinates": [
        _carre(170.0, 55.0, 9.0)["coordinates"],
        _carre(-179.0, 55.0, 9.0)["coordinates"],
    ]}
    geo_path.write_text(json.dumps(geo), "utf-8")
    dist = projet / "dist"

    resultat = build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert resultat["metas"] == 1
    assert _manifeste(dist)["meta_count"] == 1


def test_the_licence_page_is_published(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert (dist / "licence.html").exists()


def test_the_404_page_is_published_with_its_placeholders_substituted(projet):
    """Without it in the template loop, Cloudflare falls back to its default and any
    unknown address returns the home page with a 200."""
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    page = dist / "404.html"
    assert page.exists()
    texte = page.read_text("utf-8")
    assert "__CSS__" not in texte
    assert re.search(r'href=./style\.[0-9a-f]{8}\.css.', texte)


def test_the_real_404_page_references_its_assets_absolutely():
    """The defect this test stops from coming back.

    Cloudflare serves the 404 page under the unknown address that was requested, not
    under `/404.html`. Since the placeholders become bare file names, an
    `href="__CSS__"` would resolve, on `/a/b/c`, to `/a/b/style.<hash>.css`: the error
    page would arrive without styling or icon, and its back link would point at `/a/b/`.
    Only the leading slash avoids it — and only the other two pages, served at the root,
    can do without it.

    The check is on the template actually shipped, not on the fixture: it is in
    `viewer/404.html` that the regression would happen.
    """
    texte = (Path(__file__).resolve().parents[1] / "viewer" / "404.html").read_text("utf-8")

    marqueurs = [m for m in ("__CSS__", "__ICON_SVG__", "__ICON_PNG__") if m in texte]
    assert marqueurs, "the 404 page references no asset: placeholders renamed?"
    for marqueur in marqueurs:
        for occurrence in re.finditer(re.escape(marqueur), texte):
            assert texte[occurrence.start() - 1] == "/", (
                f"{marqueur} must be preceded by a slash in 404.html"
            )
    assert 'href="/"' in texte, "the back link must be absolute"


def test_the_manifest_references_files_that_exist(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    assert (dist / "data" / manifeste["index"]).exists()
    for entree in manifeste["countries"].values():
        assert (dist / "data" / entree["file"]).exists()


def test_every_referenced_image_exists(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    base = manifeste["image_base"]
    for entree in manifeste["countries"].values():
        pays = json.loads((dist / "data" / entree["file"]).read_text("utf-8"))
        for meta in pays["metas"].values():
            assert (dist / base / meta["thumb"]).exists()
            assert (dist / base / meta["full"]).exists()


def test_the_meta_no_longer_carries_the_source_path_after_the_build(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    pays = json.loads(
        (dist / "data" / manifeste["countries"]["PL"]["file"]).read_text("utf-8")
    )
    assert "image_source" not in pays["metas"]["pl1"]


def test_image_base_is_in_the_manifest(projet):
    """The workaround for the file cap: moving the images touches only this."""
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert _manifeste(dist)["image_base"] == "img/"


def test_a_custom_image_base_does_not_move_the_images_on_disk(projet):
    """The escape hatch for the file cap: changing `image_base` must only change the
    prefix written into the manifest. The images are still always written under
    `out_dir / IMAGE_BASE`, ready to be synced to a bucket with no code change."""
    dist = projet / "dist"

    build_site(
        projet / "data", dist, projet / "viewer", ["PL"],
        image_base="https://cdn.example/i/",
    )

    assert _manifeste(dist)["image_base"] == "https://cdn.example/i/"
    assert (dist / "img" / "PL").exists()


def test_the_templates_receive_the_fingerprinted_names(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    page = (dist / "index.html").read_text("utf-8")
    assert "__CSS__" not in page and "__JS__" not in page
    assert "style." in page and ".css" in page


def test_the_favicons_are_published_fingerprinted_and_referenced(projet):
    """The browser tab must carry the pin, on both pages.

    Both formats are declared: SVG for recent browsers, PNG as a fallback. A
    non-fingerprinted favicon would be served immutable for a year with no way to
    replace it, hence going through the same mechanism as everything else.
    """
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    svg = [p.name for p in dist.glob("favicon.*.svg")]
    png = [p.name for p in dist.glob("favicon.*.png")]
    assert len(svg) == 1 and len(png) == 1, f"expected one of each: {svg} {png}"

    for page in ("index.html", "licence.html"):
        texte = (dist / page).read_text("utf-8")
        assert "__ICON_SVG__" not in texte, f"placeholder not substituted in {page}"
        assert svg[0] in texte, f"{page} does not reference {svg[0]}"

    # And they must fall under an immutable cache rule, like the other fingerprinted
    # assets.
    regles = _regles((dist / "_headers").read_text("utf-8"))
    for nom in (svg[0], png[0]):
        couvrant = [
            entetes for motif, entetes in regles
            if fnmatch.fnmatchcase("/" + nom, motif)
        ]
        assert couvrant, f"no rule covers /{nom}"
        assert all("immutable" in e["Cache-Control"] for e in couvrant)


def test_the_open_graph_tags_carry_absolute_urls(projet):
    """A relative `og:image` is ignored by most preview crawlers: the shared link then
    shows up without a thumbnail. So the substitution has to produce an absolute URL,
    fingerprinted image included."""
    dist = projet / "dist"

    build_site(
        projet / "data", dist, projet / "viewer", ["PL"],
        site_url="https://exemple.test/",
    )

    page = (dist / "index.html").read_text("utf-8")
    assert "__SITE_URL__" not in page and "__OG_IMAGE__" not in page
    og = [p.name for p in dist.glob("og.*.png")]
    assert len(og) == 1

    # The preview image URL must be absolute AND carry the fingerprinted name: the two
    # substitutions compose in the right order.
    assert f"https://exemple.test/{og[0]}" in page
    # The setting's trailing slash must not produce a double slash, which would break
    # the URL for some preview crawlers.
    assert "https://exemple.test//" not in page
    assert "Find all relevant metas" in page

    licence = (dist / "licence.html").read_text("utf-8")
    assert "__SITE_URL__" not in licence


def test_the_headers_file_is_produced_with_both_regimes(projet):
    """The manifest must be revalidated on every visit, and it alone.

    A pattern that also matched `/data/manifest.json` on top of the dedicated rule would
    make the applied regime depend on a Cloudflare priority undocumented in this
    repository — potentially `immutable`, which would freeze the site on a stale manifest
    forever.
    """
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    regles = _regles((dist / "_headers").read_text("utf-8"))

    correspondances = [
        (motif, entetes) for motif, entetes in regles
        if fnmatch.fnmatchcase("/data/manifest.json", motif)
    ]
    assert len(correspondances) == 1, (
        f"exactly one pattern must match the manifest: {correspondances}"
    )
    motif, entetes = correspondances[0]
    assert motif == "/data/manifest.json"
    assert entetes["Cache-Control"] == "no-cache"

    # The fingerprinted files, meanwhile, must stay in an immutable cache for a year.
    empreinte = [
        (motif, entetes) for motif, entetes in regles
        if fnmatch.fnmatchcase("/data/h/index.a1b2c3d4.json", motif)
    ]
    assert len(empreinte) == 1
    assert "immutable" in empreinte[0][1]["Cache-Control"]

    # The HTML pages must be covered under BOTH THEIR FORMS. Cloudflare Pages serves
    # clean URLs and redirects `/licence.html` to `/licence`: so a rule written on the
    # file name alone only covers the address nobody visits. Verified in production
    # before being fixed here.
    for chemin in ("/", "/index.html", "/licence", "/licence.html", "/404", "/404.html"):
        couvrant = [
            (motif, entetes) for motif, entetes in regles
            if fnmatch.fnmatchcase(chemin, motif)
        ]
        assert couvrant, f"no rule covers {chemin}"
        assert all(e["Cache-Control"] == "no-cache" for _, e in couvrant), (
            f"{chemin} must be revalidated: {couvrant}"
        )


def test_dumps_is_independent_of_key_order():
    """Sorting the keys makes the fingerprint reproducible.

    Without it, insertion order alone would be enough to change the file name — and thus
    to flush every visitor's cache — without any content having changed.
    """
    assert _dumps({"b": 1, "a": 2}) == _dumps({"a": 2, "b": 1})


def test_two_identical_builds_give_the_same_names(projet):
    build_site(projet / "data", projet / "d1", projet / "viewer", ["PL"])
    build_site(projet / "data", projet / "d2", projet / "viewer", ["PL"])

    m1, m2 = _manifeste(projet / "d1"), _manifeste(projet / "d2")
    assert m1["index"] == m2["index"]
    # `countries` is the only fingerprinted payload that carries dictionaries (`metas`,
    # `geometries`) rather than plain lists — the only place a missing key sort could
    # show.
    assert m1["countries"] == m2["countries"]


def test_skip_images_produces_no_image(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"], skip_images=True)

    assert not (dist / "img").exists()


def test_the_result_counts_the_files_produced(projet):
    resultat = build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    assert resultat["metas"] == 1
    assert resultat["files"] > 0
    assert FILE_COUNT_WARNING < FILE_COUNT_LIMIT


def test_a_missing_source_image_raises_with_the_meta_name(projet):
    (projet / "input" / "pl1.png").unlink()

    with pytest.raises(SystemExit, match="pl1"):
        build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])


def test_a_rerun_build_overwrites_without_leaving_leftovers(projet):
    dist = projet / "dist"
    build_site(projet / "data", dist, projet / "viewer", ["PL"])
    (dist / "data" / "vieux.json").write_text("{}", "utf-8")

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert not (dist / "data" / "vieux.json").exists()
    # A genuine previous build output is still replaced without the overwrite safety
    # rail (see below) standing in the way.
    assert (dist / "_headers").exists()


def test_the_build_refuses_to_wipe_a_folder_that_does_not_look_like_an_output(projet):
    """`--out` pointing by mistake at `viewer/` or at `data/` (a swap with `--data`)
    must never be wiped: only a folder that already bears the mark of a previous build
    (`_headers`) is."""
    cible = projet / "cible"
    cible.mkdir()
    (cible / "important.txt").write_text("irreplaceable work", "utf-8")

    with pytest.raises(SystemExit, match="_headers"):
        build_site(projet / "data", cible, projet / "viewer", ["PL"])

    assert (cible / "important.txt").exists()


# --- Integrity check of the dist/ (a non-regression check on the real failure: a
# truncated `dist/` that nonetheless declares itself complete) --------------

def _arbre_complet(out_dir: Path) -> dict:
    """Build by hand a minimal but complete `dist/`, with its manifest, without going
    through `build_site`: the pure function has to be testable on any tree, not only on
    its own output.
    """
    (out_dir / "data" / "h" / "c").mkdir(parents=True)
    (out_dir / "data" / "h" / "index.json").write_text("{}", "utf-8")
    (out_dir / "img" / "PL").mkdir(parents=True)
    (out_dir / "img" / "PL" / "m1.thumb.avif").write_bytes(b"x")
    (out_dir / "img" / "PL" / "m1.full.avif").write_bytes(b"x")
    pays = {
        "metas": {"m1": {"thumb": "PL/m1.thumb.avif", "full": "PL/m1.full.avif"}},
        "geometries": {},
    }
    (out_dir / "data" / "h" / "c" / "PL.json").write_text(json.dumps(pays), "utf-8")
    (out_dir / "index.html").write_text("<!doctype html>", "utf-8")
    (out_dir / "_headers").write_text("", "utf-8")
    (out_dir / "app.a1b2c3d4.js").write_text("", "utf-8")
    (out_dir / "anki.a1b2c3d4.js").write_text("", "utf-8")
    (out_dir / "googleMutant.a1b2c3d4.js").write_text("", "utf-8")
    (out_dir / "style.a1b2c3d4.css").write_text("", "utf-8")
    (out_dir / "favicon.a1b2c3d4.svg").write_text("", "utf-8")
    (out_dir / "favicon.a1b2c3d4.png").write_bytes(b"")
    (out_dir / "og.a1b2c3d4.png").write_bytes(b"")
    return {
        "index": "h/index.json",
        "image_base": "img/",
        "countries": {"PL": {"file": "h/c/PL.json", "count": 1}},
    }


def test_a_complete_tree_reports_nothing_missing(tmp_path):
    manifeste = _arbre_complet(tmp_path)

    resultat = verifier_integrite(tmp_path, manifeste)

    assert resultat.manquants == []
    assert resultat.images_ignorees is False


def test_a_missing_country_file_is_reported(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "data" / "h" / "c" / "PL.json").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("PL.json" in chemin for chemin in resultat.manquants)


def test_a_missing_image_is_reported(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "img" / "PL" / "m1.thumb.avif").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("m1.thumb.avif" in chemin for chemin in resultat.manquants)


def test_a_missing_index_file_is_reported(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "data" / "h" / "index.json").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("index.json" in chemin for chemin in resultat.manquants)


def test_a_corrupted_country_file_is_reported_without_raising(tmp_path):
    """The case that motivates the check: a full disk truncates a file that keeps
    existing (it passes the `.exists()` test) but whose JSON is invalid. That has to stay
    a diagnosis inside `manquants`, never an exception that surfaces — otherwise the check
    fails precisely on the case it was built to cover."""
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "data" / "h" / "c" / "PL.json").write_text("{tronqu", "utf-8")

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("PL.json" in chemin for chemin in resultat.manquants)


def test_a_manifest_without_an_index_key_is_reported_without_raising(tmp_path):
    """Replayable after the fact also means robust to a manifest one did not produce
    oneself: a missing required key has to be diagnosed, not raise a `KeyError`."""
    manifeste = _arbre_complet(tmp_path)
    del manifeste["index"]

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("index" in chemin for chemin in resultat.manquants)


def test_a_country_without_a_file_key_is_reported_without_raising(tmp_path):
    """Same safety rail as for the missing 'index' key, but on a country entry: an
    unguarded `entree["file"]` would raise a `KeyError` instead of reporting the absence,
    contradicting the function's docstring."""
    manifeste = _arbre_complet(tmp_path)
    del manifeste["countries"]["PL"]["file"]

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("PL" in chemin and "file" in chemin for chemin in resultat.manquants)


def test_an_absolute_image_base_skips_the_images(tmp_path):
    """The object-storage escape hatch: when `image_base` is an absolute URL, the images
    no longer live under `out_dir` — checking them there would produce thousands of false
    positives. The country file and the index, meanwhile, are still always checked: they
    are always local, whatever `image_base` is."""
    (tmp_path / "data" / "h" / "c").mkdir(parents=True)
    (tmp_path / "data" / "h" / "index.json").write_text("{}", "utf-8")
    pays = {
        "metas": {"m1": {"thumb": "PL/m1.thumb.avif", "full": "PL/m1.full.avif"}},
        "geometries": {},
    }
    (tmp_path / "data" / "h" / "c" / "PL.json").write_text(json.dumps(pays), "utf-8")
    (tmp_path / "index.html").write_text("<!doctype html>", "utf-8")
    (tmp_path / "_headers").write_text("", "utf-8")
    (tmp_path / "app.a1b2c3d4.js").write_text("", "utf-8")
    (tmp_path / "anki.a1b2c3d4.js").write_text("", "utf-8")
    (tmp_path / "googleMutant.a1b2c3d4.js").write_text("", "utf-8")
    (tmp_path / "style.a1b2c3d4.css").write_text("", "utf-8")
    (tmp_path / "favicon.a1b2c3d4.svg").write_text("", "utf-8")
    (tmp_path / "favicon.a1b2c3d4.png").write_bytes(b"")
    (tmp_path / "og.a1b2c3d4.png").write_bytes(b"")
    manifeste = {
        "index": "h/index.json",
        "image_base": "https://cdn.example/i/",
        "countries": {"PL": {"file": "h/c/PL.json", "count": 1}},
    }

    resultat = verifier_integrite(tmp_path, manifeste)

    assert resultat.manquants == []
    assert resultat.images_ignorees is True


# --- The "page" part of the check (item 4 of the final review): index.html, the
# _headers and the two fingerprinted static assets are now covered, not only the paths
# referenced by the manifest. ----------------------------------------------

def test_a_missing_index_html_is_reported(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "index.html").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("index.html" in chemin for chemin in resultat.manquants)


def test_a_missing_headers_file_is_reported(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "_headers").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("_headers" in chemin for chemin in resultat.manquants)


def test_a_missing_fingerprinted_js_asset_is_reported(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "app.a1b2c3d4.js").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("app" in chemin for chemin in resultat.manquants)


def test_a_missing_fingerprinted_css_asset_is_reported(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "style.a1b2c3d4.css").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("style" in chemin for chemin in resultat.manquants)


def test_build_site_still_succeeds_with_the_integrated_check(projet):
    """The check runs on every build; on a sound project it must never fail an
    otherwise correct build."""
    resultat = build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    assert resultat["metas"] == 1


def test_build_site_raises_systemexit_when_the_check_fails(monkeypatch, projet):
    """Proves that `build_site` really does call the check (and not only that the
    function works in isolation): we replace it with a fake that reports a missing path,
    and verify that `build_site` relays the failure as a `SystemExit` rather than
    returning a mute success."""
    import cartometa.build.site as site

    appels = []

    def faux_verifier(out_dir, manifeste):
        appels.append((out_dir, manifeste))
        return site.ResultatVerification(["dist/fantome.json"], False)

    monkeypatch.setattr(site, "verifier_integrite", faux_verifier)

    with pytest.raises(SystemExit, match="fantome"):
        build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    assert appels, "build_site did not call verifier_integrite"


def _images_produites(dist: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in (dist / "img").rglob("*.webp")}


def test_a_second_build_re_encodes_no_image(projet, monkeypatch):
    """The build is incremental on encoding, not only on transfer.

    Without a cache, publishing three more metas paid again for encoding the ~3844 images
    already produced by the previous build — most of the ten minutes of a publication.
    """
    build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])
    avant = _images_produites(projet / "dist")
    assert avant, "the first build produced no image"

    import cartometa.build.images as images

    def interdit(*args, **kwargs):
        raise AssertionError("image re-encoded although the cache held it")

    monkeypatch.setattr(images, "_encode", interdit)

    build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    assert _images_produites(projet / "dist") == avant


def test_the_image_cache_lives_outside_dist(projet):
    """`dist/` is wiped on every build: a cache living there would never be used
    twice."""
    build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    entrees = list((projet / "data" / "cache" / "images").rglob("*.webp"))

    assert entrees, "no cache entry written"
    assert not list((projet / "dist").rglob("*.part"))


def test_without_a_google_key_the_manifest_carries_none(projet):
    """The front end's "Google" button only appears if a key exists.

    A contributor builds the site without a key: their preview must stay whole, simply
    missing the second base map.
    """
    build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    assert "google_key" not in _manifeste(projet / "dist")


def test_the_google_key_reaches_the_manifest(projet):
    """The key travels through the build, never through the repository: it will end up
    in the shipped JavaScript anyway, but not in git history."""
    build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"],
               google_key="AIzaSyFausseCle")

    assert _manifeste(projet / "dist")["google_key"] == "AIzaSyFausseCle"


def test_the_google_plugin_is_published_and_referenced(projet):
    """Loaded on demand by the front end, hence named by the manifest and not by a
    script tag: without that, every visitor would download it."""
    build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    nom = _manifeste(projet / "dist")["google_mutant"]

    assert (projet / "dist" / nom).exists()
    assert nom.startswith("googleMutant.") and nom.endswith(".js")


def test_the_natural_earth_outline_is_published(projet, monkeypatch):
    """The build wires `country_geometry` into `build_dataset`: that is the only place
    the two meet, hence the only test that proves it."""
    from shapely.geometry import box

    monkeypatch.setattr(
        "cartometa.build.site.country_geometry",
        lambda code, cache_dir: box(0.0, 0.0, 5.0, 5.0),
    )
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert _fichier_pays(dist, "PL")["outline"]["type"] == "Polygon"


def test_a_country_unknown_to_natural_earth_publishes_without_an_outline(projet, monkeypatch):
    """`country_geometry` raises KeyError for a code outside the dataset: the mini-map
    loses its background, never the country its publication."""
    def _introuvable(code, cache_dir):
        raise KeyError(code)

    monkeypatch.setattr("cartometa.build.site.country_geometry", _introuvable)
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert "outline" not in _fichier_pays(dist, "PL")


def test_an_unreachable_natural_earth_does_not_break_the_build(projet, monkeypatch):
    """A fresh clone built offline does not have the dataset cached: the download fails
    with an OSError and the site must come out anyway."""
    def _hors_ligne(code, cache_dir):
        raise OSError("network down")

    monkeypatch.setattr("cartometa.build.site.country_geometry", _hors_ligne)
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert "outline" not in _fichier_pays(dist, "PL")


def test_a_slashed_rmrg_id_yields_a_flat_image_name(projet):
    """RMRG meta ids are paths ("agriculture/dung-piles"): used raw as an image
    stem they would create subdirectories under dist/img/<CC>/ — the first build
    with RMRG data died on exactly that. The stem must be flattened; the viewer
    consumes whatever string lands in `thumb`/`full`, so nothing else moves."""
    data = projet / "data"
    Image.new("RGB", (1000, 500), (40, 50, 60)).save(projet / "input" / "bd1.png")
    (data / "metas" / "BD-rmrg.json").write_text(json.dumps([{
        "id": "agriculture/dung-piles", "tier": "regional", "title": "Dung piles",
        "description": "desc", "category": "vegetation", "origin": "rmrg",
        "image": "input/bd1.png",
        "source_url": "https://rmrg.me/bangladesh/#agriculture/dung-piles",
    }]), "utf-8")
    (data / "geo" / "BD.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "agriculture/dung-piles",
                                     "status": "validé", "pieces": []},
                      "geometry": _carre(89.0, 23.0, 2.0)}],
    }), "utf-8")
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["BD", "PL"])

    pays = _fichier_pays(dist, "BD")
    meta = pays["metas"]["agriculture/dung-piles"]
    # The id keeps its slash (it is the key, the anchor, the geo link) - only
    # the image file name is flattened.
    assert "/" not in meta["thumb"].removeprefix("BD/")
    assert (dist / "img" / meta["thumb"]).exists()
    assert (dist / "img" / meta["full"]).exists()
