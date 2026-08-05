# Adding a meta by hand

A walkthrough for a new contributor, starting from nothing: from installation
to pull request. Count ~20 min for the first meta, ~2 min for the next ones.

A manual meta is **five things**:

| | |
|---|---|
| a title | short, what you see |
| a description | what it lets you deduce |
| a category | one of six, fixed |
| an image *(optional)* | the screenshot showing the clue |
| **a footprint** | the area of the globe where the meta applies — drawn with the mouse |

The footprint is the only part you do not type in, and it is the one that has
value: a meta without a footprint is never published.

---

## 1. Install, once

You need **git**, **Python ≥ 3.14** and **[uv](https://docs.astral.sh/uv/)**.
`uv` installs Python by itself if needed.

```
git clone https://github.com/PierreSmague/cartometa.git
cd cartometa
uv sync
```

Check:

```
uv run python -m pytest
```

Everything must pass. Do not write `uv run pytest`: on some Windows machines
an application control policy makes it fail (`os error 4551`).
`python -m pytest` works everywhere.

Nothing else to install: no Node, no Cloudflare account. Publishing the site
is the maintainer's job.

---

## 2. Open the drawing interface

```
uv run cartometa-review FR
```

`FR` is the country's **ISO 3166-1 alpha-2** code as Natural Earth knows it
(`FR`, `BW`, `KR`…). Case does not matter, it is upper-cased.

Then <http://127.0.0.1:8799> in the browser. The server only listens on the
loopback interface.

The country needs **nothing** beforehand: no imported text, no existing file.
An empty queue is a valid starting point — that is exactly the "starting from
nothing" case. Files are created on the first save.

Two downloads happen on first use, once and for all, into `data/cache/`:

- the country silhouettes (Natural Earth admin-0), on the first framing;
- the administrative regions (admin-1, **41 MB**), on the first press of `S`.

`Ctrl+C` in the terminal stops the server. Everything is already written to
disk as you go: there is no "save before quitting".

---

## 3. Enter the meta

Press `N` (focus must be on the page, not in a field). The form opens.

| Field | Rule |
|---|---|
| **Title** | required |
| **Description** | required |
| **Category** | one of the seven below — no other value |
| **Source (URL)** | optional; left empty, no link shows on the site |
| **Image** | optional: `Ctrl+V` to paste a screenshot, or drag a file onto the dashed frame |

| Slug | Shown on the site as | What belongs in it |
|---|---|---|
| `infrastructure` | Infrastructures | Poles, bollards, signs, road markings, guardrails, kerbs, bridges, bus stops, power lines, meter boxes, road numbering, driving side, public transport |
| `vegetation` | Vegetation & Agriculture | Any vegetation, cultivated or wild: crops, orchards, plantations, greenhouses, forests, bush, grassland |
| `landscape` | Landscape | Relief, hydrography, climate: mountains, valleys, lakes, coasts, deserts, volcanoes, snow |
| `architecture` | Architecture | Anything built: houses, roofs, facades, walls, churches, silos, monuments, ruins |
| `car` | Car meta | The Google vehicle and its capture: camera, antenna, blur, coverage generations, trekker, number plates |
| `culture` | Culture | The immaterial: language, writing systems, flags, religion, dialling codes, toponymy, brands |
| `autre` | Other | What none of the six covers: administrative facts, context notes |

Only `autre` keeps a French spelling. It is the stored value for thousands of
metas, and renaming it would migrate most of the corpus for a cosmetic gain.

If the form files your meta in the wrong category, do not fight it: pick the
closest one, then add the correction to `data/categories.json`, keyed by country
then by meta id.

```json
{ "FR": { "Izqw": "landscape" } }
```

That file is versioned and applied when the site is built, so it survives the
regeneration of `data/metas/` that a future `cartometa-extract` performs — a
category changed only in `metas.json` would be silently lost.

The category **guesses itself** while you type the title and the description.
As soon as you pick one from the list, inference goes quiet for good: an
explicit choice is never overwritten.

Constraints on the image: **PNG, JPEG, WEBP or GIF**, **8 MB maximum**. A
normal screenshot is far below that. If the image is refused the meta is still
created (the message says so) — you can complete it later by editing
`data/manual/<CC>/metas.json`.

`Create` saves. `Escape` or `Cancel` closes without writing anything.

The meta you created **goes straight to the front of the queue**: you draw it
right away, while the source is still in front of you.

### Writing well

- **Title**: what the eye sees, not the conclusion. "White bollard with a red
  band", not "We are in Portugal".
- **Description**: self-contained. A site reader sees the thumbnail and the
  text, nothing else — neither the country nor the context of your session.
- **Image**: crop to the clue. A full-width Street View screenshot where the
  pole is twelve pixels wide teaches nothing.
- **Scope**: one meta = one area. If the clue holds for three disjoint regions
  with variations, that is usually three metas.

---

## 4. Draw the footprint

This is the heart of the work. The map is on the right, the source on the left.

| Key | Action |
|---|---|
| `D` | **rectangle** — two clicks lay down a piece |
| `C` | **freehand outline** — successive clicks; closed by returning to the first vertex, or with `Enter` |
| `S` | **subdivisions** — each click adds/removes the administrative region under the cursor |
| `E` | adds the **whole-country silhouette** |
| `F` | **clips** the area to the country borders; press again to undo the clipping |
| `Backspace` | removes the last piece, or the last vertex of an outline in progress |
| `Escape` | leaves the drawing mode without erasing anything |
| `0` | empties the area in progress |
| `A` | **saves** |
| `R` | **rejects** the meta |
| `Space` / `Shift+Space` | next / previous meta |
| `U` | undoes the last decision |
| `N` | new manual meta |

Modes are **sticky**: once a rectangle is laid down, laying the next one takes
no keypress.

A footprint is **the union of its pieces** — two disjoint rectangles, three
regions, a freehand outline plus the whole country. Mix them freely.

`F` is the shortcut that saves you from tracing a coastline click by click:
lay down a big rectangle spilling into the sea and the neighbours, then clip.
Clipping stays active while the area is being built, and the map then shows
the clipped result — that is, **exactly what `A` will save**. The computation
is done server-side on the Natural Earth silhouette, never in the browser.

The **blue dot**, when it is there, is the ground truth: the position of the
meta's Maps link. A hand-entered meta has none — the map then frames the
country.

### The drawing decides the scope — careful

The site's "national / regional" filter is derived **from the drawing alone**,
not from a checkbox:

- footprint made of the **sole** "whole country" piece (`E`) → **national**;
- **everything else**, including a clipped or completed country → **regional**.

So: if the meta holds for the whole country, press `E` and nothing else. Do
not add a rectangle "to be safe" — it would flip it to regional.

`A` on an empty area refuses to save and says so ("No piece laid down: nothing
to save."). `R` is for metas that have no business being published: they stay
in the files, marked `rejeté` — the status values are stored data and keep
their French spelling — and never come out in the site.

---

## 5. What got written to disk

For a country `FR`, after one meta created and drawn:

```
data/manual/FR/metas.json          title, description, category, source
data/manual/FR/images/man-xxxx.png your image
data/geo/FR.geojson                the footprint, its status, its pieces
```

Your identifier has the form `man-xxxx` (four hexadecimal characters). The
`man-` prefix makes any collision with identifiers imported from Plonk It
impossible.

**These three paths are versioned by git** — this is your contribution, it is
irreplaceable. Conversely, `input/`, `data/metas/`, `data/cache/` and `dist/`
are ignored: do not try to commit them.

`data/geo/FR.geojson` keeps the *pieces* as you laid them down, not just the
final geometry. That is what makes it possible to reopen a footprint and
remove a piece from it without redrawing everything:

```
uv run cartometa-review FR --all
```

reopens **every** meta of the country, including the ones already drawn or
rejected, with their pieces. Without `--all`, the queue only holds what is
left to decide.

---

## 6. Check in the real site

**Always with your country code.** `cartometa-build` without an argument
fails on a fresh clone, and that is expected — see the box just below.

```
uv run cartometa-build FR
python -m http.server 8010 --directory dist
```

then <http://127.0.0.1:8010/>. Click inside your area: your meta must show up
in the gallery, with its image and its description, and respond to the
category and scope filters.

### Your preview only holds your own metas — that is normal

The repository versions **the footprints** (`data/geo/`, 52 countries, 1922
footprints) but **not the Plonk It texts** that go with them (`data/metas/` is
gitignored, personal use). So a fresh clone has the outlines of 52 countries
and the text of none.

Two consequences, both expected:

- `uv run cartometa-build` **without an argument** walks the 52 countries and
  stops on the first one, with the message
  *"AE: 18 versioned footprint(s), but no meta text."* This is not a failure
  and you broke nothing. Give your country code.
- `uv run cartometa-build FR` builds a site holding **only** your own metas.
  If you add a meta to a country that is already filled in (`AE`), the preview
  will show your single meta and not the other 18: their texts are absent from
  your clone. The published site will have them all — the maintainer builds
  from a complete copy.

None of this affects your contribution: what you deliver are the footprints
and the manual texts, not the `dist/`.

Useful options: `--skip-images` skips re-encoding (much faster if only the
drawing interests you), `--simplify-tolerance` tunes outline detail (default
0.01°).

Never run **two builds in parallel**: the `dist/` folder is wiped at the start
of a build, and a collision truncates the output silently.

**Shortened** Google Maps links (`maps.app.goo.gl`) pasted into the header bar
fail with this static server: resolving them needs the Cloudflare runtime
(`npx wrangler pages dev dist`). Of no interest for entering metas.

---

## 7. Offering the contribution

**You do not need to know what a *fork* is.** On this repository you are given
the right to create branches directly.

### a. Request access, once

[Open an issue](https://github.com/PierreSmague/cartometa/issues/new) stating
your GitHub username and the country or countries you are interested in. You
will get an invitation by email — accept it, and that is settled for good.

Until the invitation is accepted, the `git push` of step *c* will fail with
`403` or `Permission denied`. That is the only symptom, and it means nothing
other than "access is not active yet".

What that access lets you do, and what it does not:

| | |
|---|---|
| Create a branch and push to it | yes |
| Open a pull request | yes |
| Push straight to `master` | **no**, never |
| Merge your own pull request | **no** — only the maintainer approves |

So you cannot break anything: neither the live site nor anyone else's work.

### b. Branch

```
git switch -c meta-fr-bollards
```

If `git switch` does not exist on your machine (Git older than 2.23), the
equivalent form is `git checkout -b meta-fr-bollards`.

This command is **purely local**: it creates a branch on your disk, contacts
no server, and always succeeds. If something is refused, it is never here.

### c. Commit and push

```
git add data/manual/FR data/geo/FR.geojson
git commit -m "feat: three manual metas for France"
git push -u origin meta-fr-bollards
```

A commit must contain **only** `data/manual/**` and `data/geo/*.geojson` — if
`git status` shows anything else, something is wrong.

### d. Open the pull request

`git push` prints a ready-made URL: open it, it creates the pull request.
GitHub also offers a banner on the repository page. From the command line:

```
gh pr create
```

The maintainer reviews, then merges. There is nothing else for you to do —
and nothing else you *can* do: merging into `master` requires their approval.

### Catching up later

```
git switch master
git pull
```

`master` only accepts merges through pull requests approved by the maintainer:
nobody, not even a long-standing contributor, can push to it directly.

**Licence.** By offering a contribution you agree to it being published under
**CC BY-NC-SA 4.0**, like the rest of the project's data. This is an
obligation of the source's licence, not a choice. The code itself stays MIT.

**Do not copy an image you do not have the right to use.** A Street View
screenshot you took yourself, yes. An image picked up on a third-party site
without a compatible licence, no.

And, the project's absolute rule: **never write a crawler for plonkit.net**.
Their `robots.txt` disallows everything, and Cloudflare answers 403. Source
pages are captured by hand, one at a time, with `Ctrl+S`.

---

## Common failures

Messages are quoted as the tool prints them.

| Symptom | Cause and cure |
|---|---|
| `uv run pytest` → `os error 4551` | Windows policy. Use `uv run python -m pytest`. |
| "Cannot frame the map" / `country not found in Natural Earth` | The ISO code does not exist in the admin-0 set. Check the alpha-2. |
| "admin-1 download failed" | The 41 MB set could not be fetched. Check the network and press `S` again. |
| "No piece laid down: nothing to save." | `A` on an empty area. Lay down at least one piece. |
| "image format not accepted" | PNG, JPEG, WEBP, GIF only. |
| "image too large" | 8 MB cap. Crop it, or re-save as JPEG. |
| "Meta created, but image refused" | The meta exists, only the image is missing. Complete it in `data/manual/<CC>/metas.json`, `image` field. |
| `Permission to PierreSmague/cartometa.git denied` / `403` on `git push` | Your access is not active yet: request it, then accept the invitation sent by email. See §7a. |
| `git: 'switch' is not a git command` | Git older than 2.23. Use `git checkout -b <branch>`. |
| `error: src refspec ... does not match any` | Nothing was committed: `git commit` before `git push`. |
| The queue is empty on startup | Normal for a brand-new country. Press `N`. |
| `AE: … versioned footprint(s), but no meta text.` | `cartometa-build` was run **without a country code** on a fresh clone. Expected. Re-run `uv run cartometa-build <YOUR_CODE>`. |

---

## Cheat sheet

```
uv sync                          # once
uv run cartometa-review FR       # N → enter, D/C/S/E/F → draw, A → save
uv run cartometa-build FR        # check (the country code is mandatory)
python -m http.server 8010 --directory dist

git switch -c meta-fr            # access requested and invitation accepted
git add data/manual/FR data/geo/FR.geojson
git commit -m "feat: manual metas for France"
git push -u origin meta-fr
gh pr create
```
