# Parsing a guide into metas

How to turn a whole guide — a Word document, a spreadsheet, a PDF, a saved web
page — into metas that are ready to trace, without entering them one at a time
in the review form.

The split is deliberate: **everything except the footprint** is prepared in
batch, and the footprints are then drawn by hand at review time, one meta at a
time. Nothing here writes to `data/geo/`.

Read [Adding a meta by hand](adding-a-meta-by-hand.md) first: this is the bulk
version of the same thing, and it does not repeat the categories, the drawing
keys or the pull request.

---

## The three steps

```
1. drop the document in input/to_parse/
2. uv run python scripts/parse_doc.py --list      # the file gets a no.
   uv run python scripts/parse_doc.py 1           # → transcript + images
3. write the draft, one line per meta
   uv run python scripts/stage_metas.py KE --draft draft.tsv \
       --media input/to_parse/_staged/<slug>/media
4. uv run cartometa-review KE                     # draw, A to save
```

Handled formats: `.docx`, `.xlsx`, `.pptx`, `.htm` / `.html`, `.json`,
`.txt` / `.md`, and `.pdf` if `pymupdf` is installed
(`uv add --group dev pymupdf` — it is not a project dependency).

Saved Plonk It and RMRG pages have their **own** extractors
(`cartometa-extract`, `cartometa-extract-rmrg`) which recover the sections, the
tiers and the Maps links. Use those, not this. `parse_doc.py` is for everything
else.

### Step 2 — the transcript

`parse_doc.py 1` writes, into `input/to_parse/_staged/<slug>/`:

| | |
|---|---|
| `transcript.md` | the text in reading order, headings kept, one `[img: name]` marker where each picture sits |
| `media/` | the pictures themselves, under the names the markers use |

The point of the marker is that the pairing *text ↔ screenshot* is positional,
and position is the only thing that carries it. So the transcript is read once,
and an image is designated by its file name — never loaded.

For a spreadsheet, rows come out as `r12: a<TAB>b<TAB>c` and an anchored picture
is announced on the row it starts on. Row numbers are the sheet's own, so a
skipped row means an empty row.

For a slide deck the transcript is already paired:

```
## slide 39
### Salvador
80% round, 20% ladder.
[img: image115.png, image114.png, image116.png] Black/yellow bollards very common.
[img: image117.png] Unique sidewalk (can have other black and white broken tile patterns).
[img: image200.png] (no caption)
```

Nothing on a slide is in reading order — the shape tree is in z-order, and the
pairing *picture ↔ caption* is carried by position alone. So it is resolved at
extraction: a caption is the text under the frame sharing its left edge, one
caption may name a whole row of frames, and text sharing the title's line is a
statement about the slide, not about any picture. A frame nothing points at is
marked `(no caption)` rather than silently given its neighbour's text.

Expect to look at those. `(no caption)` frames, and slides whose only text is a
place name, cannot be described from the transcript — build a labelled contact
sheet of that slide's media and read it, rather than inventing a description.

`input/` is gitignored in full: the transcript and the extracted media are
working files, and no commit can pick them up by accident.

### Step 3 — the draft

One tab-separated line per meta, five columns:

```
image<TAB>category<TAB>title<TAB>description<TAB>maps_url
```

| Column | Rule |
|---|---|
| `image` | a file name from `media/`, or empty |
| `category` | one of the seven slugs, or **empty to let the project infer it** |
| `title` | required |
| `description` | required |
| `maps_url` | a Google Maps link, or empty |

Blank lines and `#` comments are ignored. A line holding more than five columns
is refused rather than shifted: that is a stray tab in the text.

Leaving `category` empty runs `infer_category`, the very same rule the review
form applies while you type — not a second, divergent guess. The script reports
what it inferred; **check that report**, and fix a wrong one straight in
`data/manual/<CC>/metas.json`, which is versioned. `data/categories.json` is not
the channel here — it exists for the imported metas, whose file gets
regenerated.

`maps_url` is worth the trouble: resolved, it becomes the **blue dot**, the
ground truth that frames the map and tells you where to draw. Resolution costs
one HTTP request per link not already in `data/cache/maps_links.json`;
`--no-resolve` skips it and you draw without the dot.

Use `--dry-run` first. It validates the whole draft, reports the inferred
categories and the resolved links, and writes nothing.

**Settle `--source-url` before staging, not after.** A local `.docx` or `.pptx`
usually has a web original, and the person who handed you the file is the one who
knows its address — ask. The data is published under CC BY-NC-SA, so the link is
the guide author's credit, and adding it once the metas are written means editing
`metas.json` by hand. Link to the document, not to the page or slide the anchor in
a pasted URL happens to carry: that anchor records where the author was sitting,
and it is wrong on every meta but one.

### What step 3 writes

```
data/manual/<CC>/metas.json          appended, atomically
data/manual/<CC>/images/man-xxxx.webp   re-encoded, capped at 1600 px wide
```

Identifiers are drawn free across **all** sources of the country, imported ones
included. Images become WEBP because the folder is versioned and the site never
serves wider than 1400 px.

Nothing lands in `data/geo/`, so every staged meta shows up in the review queue
undecided, with no footprint — which is the whole point.

---

## Pitfalls

| Symptom | Cause and cure |
|---|---|
| `metas.json was rewritten while this ran — nothing has been written` | `stage_metas.py` **appends**: it reads `metas.json` then rewrites it, and something else rewrote the file in between. A review server open **on that same country** is the usual cause — stop it and run again. Nothing was lost: the write is refused rather than attempted. A review on a *different* country touches different files and is no obstacle. |
| `image(s) not found in --media` | The names come from the transcript's markers; `--media` must point at the `media/` folder of that same staging run. All missing names are reported at once. |
| `N columns for 5 expected` | A tab inside a title or a description. Take it out — the draft is tab-separated and nothing escapes. |
| `unknown category '…'` | Only the seven slugs of [the by-hand guide](adding-a-meta-by-hand.md#3-enter-the-meta), `autre` included, spelled exactly. |
| `PDF needs pymupdf` | `uv add --group dev pymupdf`, then run again. |
| `blue dots : 0/40 link(s) resolved` | No network, or the links are not Maps links. The metas are staged all the same; the dot is a comfort, not a requirement. |
| A title is announced as already present | Warning only, and it stages anyway. Two guides describing the same clue is normal; the same guide staged twice is not — check before drawing. |
| `no. 3 out of range` | The numbering only covers files sitting **directly** in `input/to_parse`, sorted by name. `--list` prints it. |
| A guide's own extent map looks like a good `overlay` | It is not one. `overlay` is decoded as UTF-8 and handed to resvg: it takes **SVG only**, and a PNG there breaks `cartometa-build` for the whole country. Put the extent in the description, which is where the person drawing reads it. |

**Sources arrive as files.** They are saved by hand, one at a time. The
project's absolute rule holds here too: never write a crawler for plonkit.net.

---

## Cheat sheet

```
uv run python scripts/parse_doc.py --list
uv run python scripts/parse_doc.py 1
uv run python scripts/stage_metas.py KE --draft draft.tsv \
    --media input/to_parse/_staged/kenya/media --dry-run
uv run python scripts/stage_metas.py KE --draft draft.tsv \
    --media input/to_parse/_staged/kenya/media --source-url https://…
uv run cartometa-review KE

git add data/manual/KE data/geo/KE.geojson
```
