# Cartometa — Meta Editor (local)

A local tool to browse and edit the content of Cartometa metas
(`data/manual/<CODE>/metas.json` and any other configured tier), then
publish the changes as a GitHub Pull Request.

**What this tool edits:** `title`, `description`, `category`,
`source_url`, and `difficulty` (new field, values `Beginner` /
`Intermediate` / `Pro`).
**What this tool never touches:** `id`, `country`, `tier`,
`extracted_at`, `origin`, `description_origin`, `image`, `maps_url`,
`maps_latlon`, `overlay` — shown read-only for context (the image is
previewed directly in the UI).

## Prerequisites

- Node.js
- [GitHub CLI (`gh`)](https://cli.github.com/) installed and authenticated:
  ```
  gh auth login
  ```
- A local clone of the `cartometa` repo, with `origin` pointing to GitHub.

## Installation

```bash
cd tools/cartometa-meta-editor
npm install
```

That's it — `config.json` is **optional**. The tool ships with defaults that
are already correct for everyone (the tool only ever lives at
`tools/cartometa-meta-editor/`, and almost everyone only needs the `manual`
tier):

```json
{
  "repoRoot": "../..",
  "tiers": [
    { "name": "manual", "dir": "data/manual" }
  ],
  "baseBranch": "master",
  "port": 4545
}
```

Only create a `config.json` (copy `config.example.json`) if you actually
need to change one of these — e.g. add a second tier, or use a different
port because `4545` is already taken:

- `repoRoot`: path **relative to this folder** to the root of the git repo.
- `tiers`: list of top-level data folders to aggregate per country, each
  relative to `repoRoot`. Add one entry per tier you want to include (e.g.
  a second entry for an `extracted` folder), each pointing at a folder
  that contains one subfolder per country with its own `metas.json`.
- `baseBranch`: the branch new edit branches are created from, and PRs are
  opened against.

## Running the tool

```bash
npm start
```

Then open `http://localhost:4545`.

## Usage

1. Pick a country from the left column.
2. Click a row to select it, or use the search box / category / difficulty
   filters. Ctrl/Cmd+click or the checkbox adds a row to the current
   selection instead of replacing it. Shift+click selects every row between
   the last row you clicked (without Shift) and the one you just
   Shift+clicked — same convention as a file manager.
3. With a **single** meta selected, edit `Title`, `Category`, `Difficulty`,
   `Source URL`, or `Description` — every change is saved to the server's
   in-memory session automatically (not yet written to disk).
4. With **multiple** metas selected, `Title` and `Description` are
   disabled (bulk-editing free text rarely makes sense), while `Category`,
   `Difficulty`, and `Source URL` apply immediately to the whole
   selection as soon as you change them.
5. When you're done with an editing session, click **Publish**. A
   confirmation panel lists every meta about to be included (title + id) —
   review it, then **Open Pull Request** to actually proceed (or Cancel to
   go back). If another country also has unpublished edits waiting, the
   panel says so: Publish only ever covers the country you currently have
   open.
6. Once confirmed, the tool:
   - checks that `gh` is ready and the repo has no unrelated pending
     changes;
   - creates a branch `meta-edit/<country>-<date>` from `baseBranch`;
   - writes the modified `metas.json` file(s) to disk (one per touched
     tier);
   - commits, pushes, then opens a Pull Request via `gh pr create`;
   - switches back to your starting branch.
7. The PR link is shown at the bottom of the screen.

## Adding this tool to the repo

This folder is meant to live at `tools/cartometa-meta-editor/` at the repo
root (that's the assumption behind `repoRoot: "../.."` in
`config.example.json`). Two files must **never** be committed (already
covered by this folder's own `.gitignore`):

- `node_modules/` — dependencies, reinstalled locally with `npm install`
- `config.json` — machine-local config (repo path, tiers, port).
  Committing it by mistake would silently break the Publish button: the
  tool refuses to publish if the repo has untracked files outside the
  ones it modifies itself.

To add the tool to the repo: place the folder under `tools/`, check that
`git status` only shows the intended files (`server.js`, `lib/`,
`public/`, `package.json`, `config.example.json`, `README.md`,
`.gitignore` — never `node_modules/` or `config.json`), then commit and
open a normal PR (`git add`, `git commit`, `git push`,
`gh pr create`) — **not** through the tool's own Publish button, which is
reserved for changes to `metas.json`.

## About `data/metas/`

The repo also contains a `data/metas/` folder (content extracted from
Plonk It via `cartometa-extract`), intentionally excluded from version
control — see the comment in `.gitignore`: third-party licensed content,
for personal use only, never versioned since the repo is public.

**This tool does not touch `data/metas/` and should not.** Only
`data/manual/` (content written by the Cartometa team) is eligible for
editing + PR publishing. If that ever changes, it would need a dedicated
mode that edits locally without ever committing/pushing those files —
not something to do silently.

## Important notes

- **Git safety:** the tool refuses to publish if the repo has changes
  unrelated to the edited file(s), so nothing else ever gets swept into
  the commit by accident.
- **Several countries at once:** opening a different country doesn't lose
  the one you were just editing — each keeps its own in-memory session
  until it's published. A small orange dot next to a country's name in the
  sidebar means it has unpublished edits, even if you're currently looking
  at a different country. The **Publish** button only ever covers the
  country currently open; the confirmation panel it opens also flags if
  *other* countries still have edits waiting, so nothing gets forgotten.
- **Crash / closed-terminal recovery:** every edit is saved to the
  server's memory immediately, and also mirrored to a local draft file
  (`.drafts/`, never committed) on disk. If the terminal is closed, the
  laptop sleeps mid-edit, or the process crashes, reopening the tool and
  picking the same country resumes right where you left off — a banner
  says when that draft was last saved. Closing the browser tab itself
  also prompts for confirmation if anything is still unpublished. Once a
  country is actually published, its draft is deleted — the edit is safe
  on the pushed branch instead.
- **Categories:** the `category` field offers autocomplete over every
  category already used across all countries, but you can also type a new
  one freely.
- **File format:** the file is rewritten with `JSON.stringify(..., null,
  2)`, matching the format already used in the current files — so no
  large reformatting diff to expect on first publish.
