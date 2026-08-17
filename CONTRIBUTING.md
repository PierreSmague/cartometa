# Contributing to Cartometa

Contributions are about metas and drawing their footprints. No need to be a
developer: the work is done with the mouse, in a local interface.

## Licence of contributions

By offering a contribution you agree to it being published under
**CC BY-NC-SA 4.0**, like the rest of the project's data. This is an
obligation of the source's licence, not a choice: Plonk It publishes under
share-alike.

The code itself stays MIT-licensed.

## Requesting access — first step

This repository does not expect you to know what a *fork* is. You are given
the right to work on it directly.

**[Open an issue](https://github.com/PierreSmague/cartometa/issues/new)**
stating your GitHub username and the country or countries you are interested
in. You will get an invitation by email: accept it, and you will be able to
create branches on the repository.

What that access lets you do, and what it does not:

| | |
|---|---|
| Create a branch and push to it | yes |
| Open a pull request | yes |
| Push straight to `master` | **no**, never |
| Merge your own pull request | **no** — only the maintainer approves |

Nothing you do on your branch can damage the live site or anyone else's work.
That is the point of this split: you can make mistakes without consequence.

## The loop

1. **Install** — you need git, Python ≥ 3.14 and [uv](https://docs.astral.sh/uv/):
   ```
   git clone https://github.com/PierreSmague/cartometa.git
   cd cartometa
   uv sync
   ```

2. **Enter and draw** — `uv run cartometa-review <CC>` (`FR`, `BE`, `JP`…)
   then <http://127.0.0.1:8799>. `N` creates a meta, the keys `D` `C` `S`
   `E` `F` draw its footprint, `A` saves it, and `M` reopens the form on a
   meta already entered to correct its texts. No prior data is needed: an
   empty country is a valid starting point.

3. **Check** — `uv run cartometa-build <CC>` then
   `python -m http.server 8010 --directory dist`. **The country code is
   mandatory**: without it the command stops on the first country whose texts
   you do not have, and that is expected.

4. **Offer it**:
   ```
   git switch -c metas-<cc>
   git add data/manual/<CC> data/geo/<CC>.geojson
   git commit -m "feat: manual metas for <country>"
   git push -u origin metas-<cc>
   ```
   `git push` prints a URL that opens the pull request. The maintainer reviews
   and merges.

A commit must contain **only** `data/manual/**` and `data/geo/*.geojson`.
If `git status` shows anything else, something is wrong.

The detailed guide, from installation to pull request, with every drawing key
and the common failures, is in
[`docs/adding-a-meta-by-hand.md`](docs/adding-a-meta-by-hand.md).

## Two absolute rules

**Never write a crawler for plonkit.net.** Their `robots.txt` disallows all
automated access and Cloudflare answers 403. Source pages are captured by
hand, one at a time, with `Ctrl+S`.

**Never commit an image you do not have the right to use.** A Street View
screenshot you took yourself, yes. An image picked up elsewhere without a
compatible licence, no.

## Publishing

Going live is done separately by the maintainer: only they hold the source
images for the whole set, so only they can build the complete site.
