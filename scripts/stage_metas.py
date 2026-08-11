"""Turn a compact draft into metas that are ready to trace.

The draft is one tab-separated line per meta — the cheapest thing a session can
write for a hundred metas:

    image<TAB>category<TAB>title<TAB>description<TAB>maps_url

`image` is a file name from the staging `media/` folder, `category` may be left
empty to let the project's own inference decide, and `maps_url` may be left
empty. Only the title and the description are required. Blank lines and lines
starting with `#` are ignored.

This script does everything that is left: it assigns free `man-xxxx`
identifiers, re-encodes the images into `data/manual/<CC>/images/`, resolves the
Maps links into the blue dot that frames the map at review time, and appends the
lot to `data/manual/<CC>/metas.json`.

    uv run python scripts/stage_metas.py KE --draft draft.tsv \
        --media input/to_parse/_staged/kenya/media --dry-run

It never touches `data/geo/`: every staged meta lands in the review queue with
no footprint, which is the whole point — the tracing is done by hand.
"""
from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from cartometa.atomic_write import write_json_atomic
from cartometa.extract.categories import CATEGORIES, infer_category
from cartometa.extract.maps_links import load_cache, resolve_maps_url, save_cache
from cartometa.models import ORIGIN_MANUAL, TIER_MANUAL, MetaRecord
from cartometa.review.manual import new_meta_id
from cartometa.review.store import CountryPaths, load_metas, read_json_list

DATA = Path("data")
COLUMNS = ("image", "category", "title", "description", "maps_url")
# The site never serves an image wider than cartometa.build.images.FULL_WIDTH
# (1400). A little headroom above it costs a few kilobytes and survives a future
# raise of that constant; going much further only inflates a versioned folder.
MAX_WIDTH = 1600
QUALITY = 82


class DraftError(ValueError):
    """The draft cannot be read: bad column count, unknown category, missing image."""


def read_draft(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for number, raw in enumerate(path.read_text("utf-8").splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) > len(COLUMNS):
            raise DraftError(
                f"line {number}: {len(fields)} columns for {len(COLUMNS)} expected "
                f"({', '.join(COLUMNS)}) — a stray tab in the text?"
            )
        row = dict(zip(COLUMNS, [field.strip() for field in fields]))
        row = {name: row.get(name, "") for name in COLUMNS}
        row["line"] = str(number)
        if not row["title"] or not row["description"]:
            raise DraftError(f"line {number}: title and description are both required")
        if row["category"] and row["category"] not in CATEGORIES:
            raise DraftError(
                f"line {number}: unknown category {row['category']!r} "
                f"(expected {', '.join(CATEGORIES)})"
            )
        rows.append(row)
    return rows


def file_witness(path: Path) -> tuple[int, int] | None:
    """Enough of a file's state to tell whether someone else has rewritten it."""
    if not path.exists():
        return None
    state = path.stat()
    return (state.st_mtime_ns, state.st_size)


def convert_image(source: Path, destination: Path) -> None:
    """Re-encode one screenshot to WEBP, capped in width."""
    with Image.open(source) as image:
        image.load()
        keeps_alpha = image.mode in ("RGBA", "LA") or "transparency" in image.info
        converted = image.convert("RGBA" if keeps_alpha else "RGB")
        if converted.width > MAX_WIDTH:
            height = round(converted.height * MAX_WIDTH / converted.width)
            converted = converted.resize((MAX_WIDTH, height), Image.LANCZOS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        converted.save(destination, "WEBP", quality=QUALITY, method=4)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("country", help="ISO 3166-1 alpha-2 code, as Natural Earth knows it")
    parser.add_argument("--draft", required=True, type=Path, help="the tab-separated draft")
    parser.add_argument("--media", type=Path, help="folder holding the images named in the draft")
    parser.add_argument("--source-url", default="", help="the guide's URL, applied to every meta")
    parser.add_argument("--no-resolve", action="store_true",
                        help="skip resolving the Maps links (no network, no blue dot)")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate and report, write nothing")
    arguments = parser.parse_args()

    paths = CountryPaths(DATA, arguments.country.upper())
    rows = read_draft(arguments.draft)

    # Missing images are reported all at once: a typo in a file name should not
    # cost one run per occurrence.
    if missing := [f"line {row['line']}: {row['image']}" for row in rows if row["image"]
                   and not (arguments.media and (arguments.media / row["image"]).exists())]:
        raise SystemExit("image(s) not found in --media:\n  " + "\n  ".join(missing))

    known = load_metas(paths)
    # This appends: read now, rewrite at the end. Anything else writing the same
    # file in between — a review server on this same country, creating a meta or
    # attaching an image — would lose whichever write landed second. Remembering
    # the file's state here lets the write refuse instead.
    witness = file_witness(paths.manual_metas)
    taken = {meta["id"] for meta in known}
    titles = {meta["title"].strip().lower() for meta in known}
    if repeats := [row["title"] for row in rows if row["title"].lower() in titles]:
        print(f"! {len(repeats)} title(s) already present for {paths.country}, "
              f"staged anyway: {', '.join(repeats[:5])}"
              + (" …" if len(repeats) > 5 else ""))

    cache_path = paths.cache / "maps_links.json"
    cache = load_cache(cache_path)
    stamp = datetime.now(timezone.utc).isoformat()
    inferred: collections.Counter = collections.Counter()
    staged: list[dict] = []
    dots = 0

    for row in rows:
        category = row["category"]
        if not category:
            category = infer_category(row["title"], row["description"])
            inferred[category] += 1
        meta_id = new_meta_id(taken)
        taken.add(meta_id)

        latlon = None
        if row["maps_url"] and not arguments.no_resolve:
            latlon = resolve_maps_url(row["maps_url"], cache)
            dots += latlon is not None

        image = None
        if row["image"]:
            destination = paths.manual_images / f"{meta_id}.webp"
            if not arguments.dry_run:
                convert_image(arguments.media / row["image"], destination)
            image = destination.as_posix()

        staged.append(MetaRecord(
            id=meta_id,
            country=paths.country,
            tier=TIER_MANUAL,
            title=row["title"],
            description=row["description"],
            category=category,
            source_url=arguments.source_url,
            extracted_at=stamp,
            # The substance comes from a guide, not from the person at the
            # keyboard — same value the tagged and RMRG imports store.
            description_origin="imported",
            origin=ORIGIN_MANUAL,
            image=image,
            maps_url=row["maps_url"] or None,
            maps_latlon=list(latlon) if latlon else None,
        ).to_dict())

    if not arguments.dry_run:
        # Checked as late as possible: the window that remains is the microseconds
        # between here and the write, instead of the whole run — the image
        # re-encoding and the link resolution take far longer than that.
        if file_witness(paths.manual_metas) != witness:
            raise SystemExit(
                f"{paths.manual_metas.as_posix()} was rewritten while this ran — "
                "nothing has been written.\nA review server on "
                f"{paths.country} is the usual cause: stop it, then run this again."
            )
        write_json_atomic(paths.manual_metas, read_json_list(paths.manual_metas) + staged)
        save_cache(cache_path, cache)

    verb = "would stage" if arguments.dry_run else "staged"
    print(f"{verb} {len(staged)} meta(s) for {paths.country} "
          f"→ {paths.manual_metas.as_posix()}")
    print(f"  images    : {sum(1 for m in staged if m['image'])}/{len(staged)}")
    print(f"  blue dots : {dots}/{sum(1 for row in rows if row['maps_url'])} link(s) resolved"
          + (" (--no-resolve)" if arguments.no_resolve else ""))
    if inferred:
        print("  categories inferred (check them): "
              + ", ".join(f"{name} {count}" for name, count in inferred.most_common()))
    print(f"\nNext: uv run cartometa-review {paths.country}   # then draw, A to save")


if __name__ == "__main__":
    main()
