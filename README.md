# Cartometa

Interactive map of GeoGuessr metas. Click a point on the globe and see every
meta that applies there, from the most specific to the most general.

**Personal use.** Texts and images come from [Plonk It](https://www.plonkit.net)
and are not versioned (`input/` and `data/metas/` are gitignored).

The code is MIT-licensed (`LICENSE`); the published data (texts, images,
footprints) is under CC BY-NC-SA 4.0 (`LICENSE-DATA`) — two different
licences, see also `viewer/licence.html`.

## Browsing the map

```
uv run cartometa-build
python -m http.server 8010 --directory dist
```

then <http://127.0.0.1:8010/>. `Ctrl+C` to stop.

Clicking the map opens a gallery of the matching metas, sorted by increasing
area. Hovering a thumbnail highlights its footprint on the map; clicking it
opens the full-size image. Filters stack: category, scope (regional /
national) and free-text search.

The seven categories are Infrastructures, Vegetation & Agriculture, Landscape,
Architecture, Car meta, Culture and Other. A meta's category is inferred from
its text by `cartometa/extract/categories.py`; `data/categories.json` overrides
that inference where it gets a meta wrong, and is applied when the site is
built.

Pasting a Google Street View or Maps link into the header bar recenters the
map on that point and shows its metas. A static server does not serve
`/api/resolve`, so **shortened links** (`maps.app.goo.gl`) fail with the
command above. Testing them locally needs the Cloudflare runtime:

```
npx wrangler pages dev dist
```

## Adding a country

Four commands, in this order. All of them are safe to re-run.

### 1. Capture the source page

Plonk It blocks all automated access (`robots.txt` disallows everything,
Cloudflare answers 403). Capture is therefore **manual**: open the country
page in your browser, `Ctrl+S`, "web page, complete", into `input/`.

Never write a crawler for that site.

### 2. Extract the metas

```
uv run cartometa-extract <country>
```

Parses the saved HTML, pulls out title, description, category, images and
Maps link, and writes `data/metas/<CC>.json`. Resolves Google Maps links into
coordinates (cached in `data/cache/`) — that is the only network access,
alongside the Natural Earth download.

The country's ISO code is derived from the slug through Natural Earth names
(`botswana` → `BW`): no country needs to be declared in the code. If the
Plonk It slug matches no Natural Earth name, the command says so and asks for
`--country XX`.

Add `--retry-failed-links` to retry links marked unresolvable.

### 3. Draw the footprints by hand

```
uv run cartometa-review <CC>
```

Serves an interface on <http://127.0.0.1:8799> (loopback only). Every meta
arrives **without geometry**: drawing its footprint is up to you.

| Key | Action |
|---|---|
| `D` | rectangle mode — two clicks lay down a piece |
| `C` | freehand outline mode — successive clicks, closed by returning to the first vertex or with `Enter` |
| `S` | subdivision mode — each click adds/removes the level-1 administrative region under the cursor |
| `E` | adds the whole-country silhouette |
| `F` | clips the area to the country borders — anything outside is dropped; press again to undo the clipping |
| `Backspace` | removes the last piece, or the last vertex if an outline is in progress |
| `Escape` | leaves the drawing mode without erasing anything |
| `0` | empties the area in progress |
| `A` | saves the union of the pieces |
| `R` | rejects the meta |
| `Space` / `Shift+Space` | next / previous meta |
| `U` | undoes the last decision |
| `N` | enters a manual meta (text + pasted or dropped image) |

Modes are **sticky**: once a rectangle is laid down, laying the next one takes
no keypress. A footprint is the union of its pieces — two disjoint rectangles,
three regions, a freehand outline plus the whole country.

`F` saves you from tracing a coastline click by click: lay down a wide
rectangle spilling into the sea and the neighbours, then clip. Clipping stays
active while the area is being built (pieces laid down afterwards are clipped
too) and the map then shows the clipped result, that is, exactly what `A` will
save. The computation is done server-side on the Natural Earth silhouette,
never in the browser.

The blue dot, when present, is the **ground truth**: the position of the
meta's Maps link.

`cartometa-review <CC> --all` reopens every meta, including the ones already
drawn, with their pieces — to go over a country again when a new source does
better.

Subdivision mode downloads the Natural Earth admin-1 dataset (41 MB) on first
use, then extracts the country's regions into `data/cache/admin1/`. Later
launches are instant.

### 4. Publish

```
uv run cartometa-build
npx wrangler pages deploy dist --project-name cartometa --branch main
```

`--branch main` is not optional: without it, `wrangler` infers the branch from
the local git repository, and anything that is not `main` goes out as a
*preview* on a `<branch>.cartometa.pages.dev` URL without touching the site.
The deployment succeeds, but `cartometa.com` stays on the previous version.

`cartometa-build` produces a self-contained, gitignored `dist/`: geometries
simplified and split per country, images in two sizes, content fingerprints
for caching. Since the source images live in `input/`, which is not versioned,
the site can only be built locally.

`dist/` is wiped on every call, but **images are re-encoded only once**. They
are kept in `data/cache/images/` (gitignored, ~230 MB at 1922 footprints),
indexed on the source content and on the encoding settings. So a publication
that only adds a few metas takes about thirty seconds instead of twelve
minutes. Changing a width or the quality in `cartometa/build/images.py`
invalidates the cache by itself. Deleting it is harmless: the next build
rebuilds it.

Useful options: `--skip-images` to iterate fast on the code,
`--simplify-tolerance` to tune outline detail (default 0.01°, capped by the
size of each footprint).

### Google base map (optional)

```
uv run cartometa-build --google-key AIza...
```

Adds an `OSM / Google` switch in the corner of the map. **OpenStreetMap stays
the default base map on every load**, and nothing from Google is requested —
no script, no map instance — until the visitor clicks. Since Google bills on
map initialisation, a visitor who stays on OSM costs nothing.

Without `--google-key` the switch does not appear: a contributor builds the
site locally without a key and still gets a complete preview. The build says
so at the end of its output, because forgetting it is silent on the site side
— the map shows up, only the second base map is missing.

Failing the option, the `CARTOMETA_GOOGLE_KEY` environment variable is read.
That is the form to prefer on a machine that publishes: since `dist/` is not
versioned, a build launched for any other reason (a fix, an optimisation)
would otherwise republish a site without the switch with nothing to remind
you.

```
setx CARTOMETA_GOOGLE_KEY AIza...        # Windows, once and for all
export CARTOMETA_GOOGLE_KEY=AIza...     # POSIX shell
```

The key is **never versioned**. It will be public in the shipped site's
`data/manifest.json` — a browser key always is — but it does not need to stay
in git history after a rotation. Two protections to set up in the Google Cloud
console, without which anyone can burn through your quota: **HTTP referrer
restriction** on your domains, and a **daily quota cap**.

The `viewer/googleMutant.js` plugin is vendored
([Leaflet.GridLayer.GoogleMutant](https://gitlab.com/IvanSanchez/Leaflet.GridLayer.GoogleMutant/),
BEER-WARE licence, author notice preserved).

### Sending a meta to Anki (optional)

Every meta opened full-size carries an "Add to Anki" button: it creates a card
(image on the front; footprint over the country silhouette, explanation and
source link on the back) in the chosen deck, through
[AnkiConnect](https://ankiweb.net/shared/info/2055492159).

On the visitor's side there are three conditions, also explained in the
collapsed "Anki integration" guide the site shows when Anki does not answer:
Anki open with AnkiConnect installed, the site's origin added to
`webCorsOriginList` in the add-on config (`https://cartometa.com`, or
`http://127.0.0.1:8010` locally), and the "local network" permission that
Chrome ≥ 142 asks for on the first call. Safari does not allow that dialog.

Two notes for development:

- AnkiConnect listens on port 8765, `cartometa-review` on 8799: Anki can stay
  open during a drawing session. They shared 8765 until the review server was
  moved, and the collision was silent — on Windows `SO_REUSEADDR` let the second
  bind succeed, so the interface announced its URL while Anki went on serving
  that port. Should any port be busy now, the command refuses to start and says
  so instead of half-starting.
- The build publishes the Natural Earth silhouette (`outline`) in each country
  file, as the mini-map's background. Country unknown to the dataset, or
  dataset unreachable: the build carries on and says so, and that country's
  mini-map is drawn without a background.

## Development

```
uv sync
uv run python -m pytest
```

`uv run pytest` fails on some Windows machines (application control policy,
`os error 4551`): do not "fix" the invocation above by dropping it,
`python -m pytest` is the form that works everywhere.

273 tests. None touches the network; the ones marked `real_data` are skipped
only if no `data/geo/*.geojson` exists. Since those files are tracked by git
they are always there: as long as no footprint has been drawn into them, those
tests run against empty files and pass without checking anything.

## Where things are

```
cartometa/build/     dataset, geometries, images, templates: cartometa-build
cartometa/extract/   HTML → structured metas, Maps link resolution
cartometa/geo/       Natural Earth reference data (countries, regions)
cartometa/review/    local review server + drawing interface
viewer/              map templates (Leaflet), assembled by cartometa-build
functions/           the only server-side code: /api/resolve follows short Maps links
data/geo/            drawn footprints + status + pieces (versioned)
data/manual/         hand-entered metas, texts and images (versioned)
data/categories.json category corrections, applied at build time (versioned)
data/metas/          Plonk It texts (never versioned, regenerable)
input/               saved pages (never versioned)
docs/                specs, plans, contribution guides
```

## Status

Automatic detection was removed on 2026-07-30: footprints are now drawn by
hand. The geometries produced by the old pipeline were deleted and have to be
redone — they remain readable in the git history, along with the measurement
report that came with them.
