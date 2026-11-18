# Car metas from carmeta — `cartometa-carmeta`

The [carmeta](https://github.com/iggedi-ig-ig/carmeta) repository publishes,
country by country, Street View locations tagged by a model: which Google car,
which year, which copyright, antenna or not… `cartometa-carmeta` turns those
tags into `car` metas with a pre-drawn footprint, which you accept or reject in
`cartometa-review` like any other proposal.

Nothing is published without you: the pipeline only reduces what reaches the
review.

```
carmeta repository (GitHub)
      │  cartometa-carmeta sync            scheduled, daily
      ▼
data/cache/carmeta/          mirror, analysis, report (gitignored)
      │  cartometa-carmeta arbitrate       by hand, when cases are waiting
      ▼
data/carmeta/rules.json      decisions, lexicon, thresholds (versioned)
      │  cartometa-carmeta import [CC …]   by hand
      ▼
data/carmeta/<CC>.json       texts of the metas (versioned)
data/geo/<CC>.geojson        footprints, status `proposé`
      │  cartometa-review <CC>             A → validated   R → rejected
      ▼
cartometa-build → wrangler   unchanged
```

## The cycle

| Step | Command | Writes |
|---|---|---|
| 1. Watch the repository | `uv run cartometa-carmeta sync` | `data/cache/carmeta/`, `logs/` only |
| 2. See where things stand | `uv run cartometa-carmeta status` | nothing |
| 3. Settle the borderline cases | `uv run cartometa-carmeta arbitrate` | `data/carmeta/rules.json` |
| 4. Write the proposals | `uv run cartometa-carmeta import [CC …]` | `data/carmeta/`, `data/geo/` |
| 5. Accept or reject | `uv run cartometa-review <CC>`, or `uv run cartometa-carmeta accept [CC …]` | `data/geo/` |
| 6. Publish | `uv run cartometa-build`, then `wrangler` | `dist/` |

`sync` is the only step that runs on its own. When the repository has not
changed it makes one network call, writes nothing and prints nothing. When it
has, it downloads what changed, redoes the analysis of the countries concerned,
writes `data/cache/carmeta/report.html`, adds a line to
`logs/carmeta-sync.log` and shows a system notification. The report is the
place to look: one small map per tag (its zones, the part of the country it
rules out) and a Street View link.

The first `sync` downloads every file of the repository, about 1.3 GB
uncompressed (transfers are compressed and resumed when cut). It makes 46 API
calls; without a token GitHub allows 60 per hour, so a first pass interrupted
by the quota is simply run again later — what was fetched is kept. Set
`GITHUB_TOKEN` to raise the quota. The full analysis of the 45 files takes
well under a minute.

`import` refuses to run while `cartometa-review` is open (both write
`data/geo/`), and `import --dry-run` shows what it would do without writing.

`accept` is the shortcut for a batch you trust: it validates every pending
carmeta proposal exactly as `A` would — pieces resolved against Natural Earth,
clipped to the borders — and adopts every pending re-proposal, without opening
any of them. Rejected metas stay rejected, and proposals that did not come
from carmeta are left in the review queue. Review a country or two first; a
meta validated this way can still be reopened with `cartometa-review <CC>
--all` and retouched or rejected.

## What the filter keeps

A tag becomes a meta when it helps the player **rule out part of the country**:

- **Families kept**: car × year, copyright, `Antenna`, `BL`/`Brakelight`,
  blurs, `Exposed`, `Snow`, `Smallcam`. Years, months, weather, country codes,
  subdivisions, climates and the `No …` tags are dropped on sight.
- **Finest level only**: `Antenna` is dropped where `Blue 2023 (A)`-style tags
  already cover it.
- **Zones**: at least 30 of the tag's points in a row. A lone point is a
  classification mistake, not a coverage.
- **Regional gain**: the share of the country ruled out on seeing the tag.
  20 % or more is kept, under 10 % dropped, in between goes to arbitration.
  A tag sprinkled everywhere gains nothing, whatever its surface.

For each country and each family, the source is the most recent file that
holds the family: a new version of a file that drops the copyrights does not
lose them, they keep coming from the previous one.

## Arbitration

`arbitrate` walks the cases the filter cannot settle alone and asks `k` (keep),
`d` (drop), `s` (skip) or `q` (quit):

- **unknown descriptors** first — a word of a car tag the lexicon does not
  know (`Truck`, `Lowcam`…). Kept, it asks for the English label used in titles;
- **borderline tags** — a gain between 10 and 20 %, one question per country.

Every answer is saved at once in `rules.json`. A decision is durable: it is
only asked again if the tag's gain later moves by more than ten points.

## `data/carmeta/rules.json`

Versioned, readable, and meant to be edited by hand.

| Key | Meaning |
|---|---|
| `thresholds.min_zone_points` | points in a row that make a zone (30) |
| `thresholds.min_capture` | minimum share of a tag's points inside its zones (0.35) |
| `thresholds.gain_drop`, `gain_keep` | the arbitration band (0.10, 0.20) |
| `thresholds.reproposal_iou` | overlap under which a validated footprint is proposed again (0.80) |
| `sources.exclude` | paths never used as a source |
| `sources.pin` | `{"AU": path}` forces a file for a country, `{"AU|copyright": path}` for one family |
| `lexicon` | per descriptor: `label` (titles), optional `phrase` (descriptions), `status` (`accepted`, `pending`, `rejected`) |
| `decisions` | `"<CC>|<tag>"` → `keep` or `drop`, with the gain it was taken on |
| `streetview_pitch` | optional; camera pitch of the Street View links (default −35) |

After changing a **threshold** or a **source**, run
`uv run cartometa-carmeta sync --force`: the analysis is cached with the rules
it was made under, and `import` refuses an analysis made under other ones.
Lexicon and decisions need no such thing: they are applied when the analysis
is read.

### A title is wrong

Car metas cannot be edited with `M` in the review: their texts are generated.
Correct the `label` (or `phrase`) of the descriptor in `rules.json` and run
`import` again — the new wording reaches every meta that uses it, validated
ones included, without touching their footprints.

## When the repository moves

| The meta is… | A new version of its file… |
|---|---|
| proposed | rewrites the proposal with the new footprint |
| rejected | changes nothing, ever |
| validated, footprint overlapping the last proposed one at 80 % or more | changes nothing |
| validated, footprint moved further | **proposes the new footprint next to the published one** |

A re-proposal never unpublishes anything. In the review the published
footprint is drawn dashed in orange under the new one: `A` adopts the new one
(retouch it first if you wish), `R` keeps the published one, and either way
the proposal is gone until the computed footprint moves again.

When a **tag disappears** — gone from the file, or now dropped by the filter —
a proposal nobody decided on is deleted, and a validated meta is kept and
listed in the report. If the coverage really is gone (a year entirely
re-shot), take it down yourself:

```
uv run cartometa-carmeta prune [CC …]
```

lists those metas with the reason and deletes each one you confirm, text and
footprint. Should the tag come back one day, it is proposed afresh.

## Installing the daily run

The job writes nowhere but `data/cache/carmeta/` and `logs/`, and runs no git
command: it can run while you work on any branch.

**macOS** — a `launchd` agent, every day at 09:00 (on waking if the Mac was
asleep):

```
scripts/install-carmeta-sync.sh
scripts/install-carmeta-sync.sh --uninstall
```

**Windows** — a Task Scheduler task, same schedule:

```
powershell -ExecutionPolicy Bypass -File scripts\install-carmeta-sync.ps1
powershell -ExecutionPolicy Bypass -File scripts\install-carmeta-sync.ps1 -Uninstall
```

Both find `uv` in your `PATH` at install time and run the command from the
repository they were installed from. The notification is best-effort; the
report and `logs/carmeta-sync.log` are the reliable trace.

## The "advanced car metas" option

On the site the metas that come from carmeta are **hidden by default**. They
are several hundred narrow footprints, and being the most specific they would
open nearly every result list. A checkbox under the filters, *Enable advanced
car metas*, shows them; the choice is remembered in the browser. When the only
metas covering a point are advanced ones, the page says so instead of claiming
the point is empty.

They are ordinary `car` metas in every other respect: the *Car meta* category
filter, the search and the pins apply to them once the option is on.

## What a car meta looks like on the site

There is no screenshot. The build draws each car meta a **tile**: its title on
a flat background in the colour the tag has on the carmeta maps — the colour
of the car — with the year on its own line. The text is white, or black when
the car is white or gray; a tag with no colour gets a white tile. The blow-up
adds a "Street View example" link to one representative panorama.

## Licence

carmeta is published under CC BY-NC 4.0, compatible with the CC BY-NC-SA of
Cartometa's data. Every car meta links back to the carmeta repository as its
source, and the site's licence page credits it.
