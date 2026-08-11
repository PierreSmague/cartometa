"""One labelled contact sheet from a staging folder's images.

A guide's uncaptioned frames cannot be described from its text, and opening two
hundred screenshots one at a time is not an option. This tiles them instead,
each labelled with the slide it came from and its file name, so one look covers
a whole slide and the name can go straight into the draft.

    uv run python scripts/contact_sheet.py input/to_parse/_staged/<slug> --slides 61 62 63
    uv run python scripts/contact_sheet.py input/to_parse/_staged/<slug> --images image7.png image8.png
    uv run python scripts/contact_sheet.py input/to_parse/_staged/<slug> --uncaptioned

Reads `transcript.md` for the grouping, writes `sheet.jpg` in the staging folder
unless told otherwise.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw

TILE = 330
PAD = 6
LABEL = 16
COLUMNS = 4
IMG_LINE = re.compile(r"\[img: ([^\]]+)\]\s*(.*)")


def read_transcript(staging: Path) -> list[tuple[str, str, bool]]:
    """(slide, image name, has a caption) for every picture, in transcript order."""
    entries: list[tuple[str, str, bool]] = []
    slide = "?"
    for line in (staging / "transcript.md").read_text("utf-8").splitlines():
        if (heading := re.match(r"## (?:slide )?(.+)", line)):
            slide = heading.group(1).strip()
        elif (found := IMG_LINE.match(line)):
            captioned = found.group(2).strip() != "(no caption)"
            for name in (n.strip() for n in found.group(1).split(",")):
                entries.append((slide, name, captioned))
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("staging", type=Path, help="a staging folder made by parse_doc.py")
    parser.add_argument("--slides", nargs="*", default=[],
                        help="only these slides (numbers as they appear in the transcript)")
    parser.add_argument("--images", nargs="*", default=[], help="only these file names")
    parser.add_argument("--uncaptioned", action="store_true",
                        help="only the pictures no caption names")
    parser.add_argument("--out", type=Path, help="output file (default <staging>/sheet.jpg)")
    arguments = parser.parse_args()

    entries = read_transcript(arguments.staging)
    if arguments.slides:
        entries = [e for e in entries if e[0] in arguments.slides]
    if arguments.images:
        entries = [e for e in entries if e[1] in arguments.images]
    if arguments.uncaptioned:
        entries = [e for e in entries if not e[2]]
    # The same file can illustrate two slides; tiling it twice teaches nothing.
    seen: set[str] = set()
    entries = [e for e in entries if not (e[1] in seen or seen.add(e[1]))]
    if not entries:
        raise SystemExit("no picture matches that selection")

    tiles = []
    for slide, name, _ in entries:
        path = arguments.staging / "media" / name
        if not path.exists():
            continue
        image = Image.open(path).convert("RGB")
        image.thumbnail((TILE, TILE))
        tiles.append((f"{slide}:{Path(name).stem}", image))

    columns = max(1, min(COLUMNS, len(tiles)))
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * (TILE + PAD) + PAD,
                              rows * (TILE + PAD + LABEL) + PAD), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(tiles):
        x = PAD + (index % columns) * (TILE + PAD)
        y = PAD + (index // columns) * (TILE + PAD + LABEL)
        draw.text((x + 2, y), label, fill="black")
        sheet.paste(image, (x + (TILE - image.width) // 2, y + LABEL))

    out = arguments.out or arguments.staging / "sheet.jpg"
    sheet.save(out, quality=88)
    print(f"{out.as_posix()}  {sheet.width}x{sheet.height}  {len(tiles)} tile(s)")


if __name__ == "__main__":
    main()
