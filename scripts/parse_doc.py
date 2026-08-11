"""Dump a source guide to a transcript that is cheap to read.

Turning a guide into metas costs one thing above all others: reading it. This
script does the mechanical half. It walks the document in reading order, writes
the text to `transcript.md`, extracts the images beside it, and marks where each
one sits — so a session pays for the text once, and can name an image without
ever loading it.

    uv run python scripts/parse_doc.py --list     # the numbering
    uv run python scripts/parse_doc.py 3          # the 3rd file of input/to_parse
    uv run python scripts/parse_doc.py some/file.docx

Handles .docx, .xlsx, .pptx, .htm/.html, .json, and .pdf if pymupdf is installed.
Output lands in `input/to_parse/_staged/<slug>/`, which git ignores like the
rest of `input/`.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import shutil
import unicodedata
import urllib.parse
import zipfile
from pathlib import Path
from xml.etree import ElementTree

TO_PARSE = Path("input/to_parse")
STAGED = TO_PARSE / "_staged"

# OOXML namespaces, by the local prefix used below. Element tags are compared
# fully qualified: a document may declare whatever prefixes it likes.
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "sml": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def slugify(name: str) -> str:
    ascii_name = (unicodedata.normalize("NFKD", name)
                  .encode("ascii", "ignore").decode("ascii"))
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "document"


# --------------------------------------------------------------------------- #
# OOXML shared plumbing (.docx and .xlsx are both zips of XML)
# --------------------------------------------------------------------------- #

def read_rels(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, bool]]:
    """Relationship id -> (target, is_external) for one part of the package."""
    folder, name = posixpath.split(part)
    rels_path = posixpath.join(folder, "_rels", name + ".rels")
    if rels_path not in archive.namelist():
        return {}
    root = ElementTree.fromstring(archive.read(rels_path))
    return {
        node.attrib["Id"]: (node.attrib["Target"],
                            node.attrib.get("TargetMode") == "External")
        for node in root.iter(q("rel", "Relationship"))
    }


class MediaSink:
    """Copies referenced package images out, once each, under their own name."""

    def __init__(self, archive: zipfile.ZipFile, media_dir: Path) -> None:
        self.archive = archive
        self.media_dir = media_dir
        self.done: dict[str, str] = {}

    def take(self, part_folder: str, target: str) -> str | None:
        """Extract the image a relationship points at; return its file name."""
        inner = posixpath.normpath(posixpath.join(part_folder, target))
        if inner in self.done:
            return self.done[inner]
        if inner not in self.archive.namelist():
            return None
        name = posixpath.basename(inner)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        (self.media_dir / name).write_bytes(self.archive.read(inner))
        self.done[inner] = name
        return name


# --------------------------------------------------------------------------- #
# .docx
# --------------------------------------------------------------------------- #

def docx_tokens(element: ElementTree.Element, rels: dict,
                media: MediaSink | None) -> list[tuple[str, str | None]]:
    """One block as (text, image) pairs in document order.

    Where a screenshot sits relative to the sentence that introduces it is the
    only clue pairing them, so the walk stays in document order rather than
    collecting the text and the images separately: `iter()` is a depth-first
    pre-order traversal, which is exactly reading order here.
    """
    tokens: list[tuple[str, str | None]] = []
    for node in element.iter():
        tag = node.tag
        if tag == q("w", "t"):
            tokens.append((node.text or "", None))
        elif tag == q("w", "tab"):
            tokens.append(("\t", None))
        elif tag in (q("w", "br"), q("w", "cr")):
            tokens.append((" ", None))
        elif media is not None:
            embed = (node.attrib.get(q("r", "embed")) if tag == q("a", "blip")
                     else node.attrib.get(q("r", "id")) if tag == q("v", "imagedata")
                     else None)
            if embed and (found := rels.get(embed)) and not found[1]:
                if (name := media.take("word", found[0])):
                    tokens.append(("", name))
    return tokens


def docx_links(element: ElementTree.Element, rels: dict) -> list[str]:
    """The external link targets of one block, deduplicated, in order."""
    links: list[str] = []
    for node in element.iter(q("w", "hyperlink")):
        target = rels.get(node.attrib.get(q("r", "id"), ""))
        if target and target[1] and target[0] not in links:
            links.append(target[0])
    return links


def docx_heading_level(paragraph: ElementTree.Element) -> int:
    style = paragraph.find(f"{q('w', 'pPr')}/{q('w', 'pStyle')}")
    value = style.attrib.get(q("w", "val"), "") if style is not None else ""
    match = re.fullmatch(r"[Hh]eading\s?(\d)", value)
    return int(match.group(1)) if match else 0


def docx_lines(archive: zipfile.ZipFile, media: MediaSink) -> list[str]:
    root = ElementTree.fromstring(archive.read("word/document.xml"))
    rels = read_rels(archive, "word/document.xml")
    body = root.find(q("w", "body"))
    lines: list[str] = []

    def emit(tokens: list[tuple[str, str | None]], links: list[str], level: int = 0) -> None:
        pending = ""

        def flush() -> None:
            nonlocal pending
            if (text := pending.strip()):
                lines.append(f"{'#' * min(level + 1, 6)} {text}" if level else text)
            pending = ""

        for text, image in tokens:
            pending += text
            if image:
                flush()
                lines.append(f"[img: {image}]")
        flush()
        for url in links:
            lines.append(f"<{url}>")

    def walk(container: ElementTree.Element) -> None:
        for child in container:
            tag = local(child.tag)
            if tag == "p":
                emit(docx_tokens(child, rels, media), docx_links(child, rels),
                     docx_heading_level(child))
            elif tag == "tbl":
                # A row is usually one meta, so its screenshots trail the whole
                # row rather than splitting it cell by cell.
                for row in child.findall(q("w", "tr")):
                    cells: list[str] = []
                    images: list[str] = []
                    links: list[str] = []
                    for cell in row.findall(q("w", "tc")):
                        tokens = docx_tokens(cell, rels, media)
                        cells.append("".join(text for text, _ in tokens).strip())
                        images += [name for _, name in tokens if name]
                        links += [url for url in docx_links(cell, rels) if url not in links]
                    emit([("| " + " | ".join(cells) + " |", None)]
                         + [("", name) for name in images], links)
            elif tag in ("sdt", "sdtContent", "txbxContent"):
                walk(child)
    walk(body if body is not None else root)
    return lines


# --------------------------------------------------------------------------- #
# .xlsx
# --------------------------------------------------------------------------- #

def xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in item.iter(q("sml", "t")))
            for item in root.iter(q("sml", "si"))]


def xlsx_cell_value(cell: ElementTree.Element, shared: list[str]) -> str:
    kind = cell.attrib.get("t", "n")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(q("sml", "t"))).strip()
    value = cell.find(q("sml", "v"))
    text = (value.text or "") if value is not None else ""
    if kind == "s" and text.isdigit() and int(text) < len(shared):
        return shared[int(text)].strip()
    return text.strip()


def xlsx_images_by_row(archive: zipfile.ZipFile, sheet_part: str,
                       media: MediaSink) -> dict[int, list[str]]:
    """Sheet images keyed by the 1-based row their anchor starts on."""
    sheet_rels = read_rels(archive, sheet_part)
    sheet_folder = posixpath.dirname(sheet_part)
    found: dict[int, list[str]] = {}
    root = ElementTree.fromstring(archive.read(sheet_part))
    for node in root.iter(q("sml", "drawing")):
        target = sheet_rels.get(node.attrib.get(q("r", "id"), ""))
        if not target or target[1]:
            continue
        drawing_part = posixpath.normpath(posixpath.join(sheet_folder, target[0]))
        if drawing_part not in archive.namelist():
            continue
        drawing_rels = read_rels(archive, drawing_part)
        drawing_folder = posixpath.dirname(drawing_part)
        drawing = ElementTree.fromstring(archive.read(drawing_part))
        for anchor in drawing:
            row_node = anchor.find(f"{q('xdr', 'from')}/{q('xdr', 'row')}")
            row = int(row_node.text or 0) + 1 if row_node is not None else 0
            for blip in anchor.iter(q("a", "blip")):
                rel = drawing_rels.get(blip.attrib.get(q("r", "embed"), ""))
                if rel and not rel[1] and (name := media.take(drawing_folder, rel[0])):
                    found.setdefault(row, []).append(name)
    return found


def xlsx_lines(archive: zipfile.ZipFile, media: MediaSink) -> list[str]:
    shared = xlsx_shared_strings(archive)
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels = read_rels(archive, "xl/workbook.xml")
    lines: list[str] = []
    for sheet in workbook.iter(q("sml", "sheet")):
        target = rels.get(sheet.attrib.get(q("r", "id"), ""))
        if not target:
            continue
        part = posixpath.normpath(posixpath.join("xl", target[0]))
        if part not in archive.namelist():
            continue
        lines.append(f"## sheet: {sheet.attrib.get('name', '?')}")
        images = xlsx_images_by_row(archive, part, media)
        root = ElementTree.fromstring(archive.read(part))
        for row in root.iter(q("sml", "row")):
            number = int(row.attrib.get("r", "0"))
            for name in images.pop(number, []):
                lines.append(f"[img: {name}]  (row {number})")
            cells = [xlsx_cell_value(c, shared) for c in row.findall(q("sml", "c"))]
            while cells and not cells[-1]:
                cells.pop()
            if cells:
                lines.append(f"r{number}: " + "\t".join(cells))
        # Anchors past the last populated row still carry a picture worth seeing.
        for number in sorted(images):
            for name in images[number]:
                lines.append(f"[img: {name}]  (row {number})")
    return lines


# --------------------------------------------------------------------------- #
# .pptx
# --------------------------------------------------------------------------- #

def drawing_text_lines(element: ElementTree.Element) -> list[str]:
    """The `a:p` paragraphs of a DrawingML shape, one line each."""
    lines: list[str] = []
    for paragraph in element.iter(q("a", "p")):
        pieces: list[str] = []
        for node in paragraph.iter():
            if node.tag == q("a", "t"):
                pieces.append(node.text or "")
            elif node.tag == q("a", "br"):
                pieces.append(" ")
        if (text := " ".join("".join(pieces).split())):
            lines.append(text)
    return lines


def drawing_links(element: ElementTree.Element, rels: dict) -> list[str]:
    links: list[str] = []
    for node in element.iter(q("a", "hlinkClick")):
        target = rels.get(node.attrib.get(q("r", "id"), ""))
        if target and target[1] and target[0] not in links:
            links.append(target[0])
    return links


EMU_PER_INCH = 914400
# How far a caption may sit from the picture it names. A slide is 10 inches
# wide, and captions here land within a tenth of an inch of the frame; an inch
# is slack, not licence.
CAPTION_GAP = EMU_PER_INCH
# A caption below its picture is the deck's convention. Beside or above happens,
# so it is allowed but must lose every tie against a caption below.
SIDE_PENALTY = EMU_PER_INCH // 2
ABOVE_PENALTY = EMU_PER_INCH
# Pictures in a row share one caption: everything within a tenth of an inch of
# the best distance is named by it too.
TIE = EMU_PER_INCH // 10


def shape_box(shape: ElementTree.Element) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) in EMU; a zero box when the frame is inherited."""
    frame = next((node for node in shape.iter() if local(node.tag) == "xfrm"), None)
    offset = frame.find(q("a", "off")) if frame is not None else None
    extent = frame.find(q("a", "ext")) if frame is not None else None
    left = int(offset.attrib.get("x", 0)) if offset is not None else 0
    top = int(offset.attrib.get("y", 0)) if offset is not None else 0
    width = int(extent.attrib.get("cx", 0)) if extent is not None else 0
    height = int(extent.attrib.get("cy", 0)) if extent is not None else 0
    return (left, top, left + width, top + height)


def is_title(shape: ElementTree.Element) -> bool:
    return any(node.attrib.get("type") in ("title", "ctrTitle")
               for node in shape.iter(q("p", "ph")))


def caption_cost(text: tuple, picture: tuple) -> int | None:
    """What it costs to read `text` as the caption of `picture`, None if it cannot."""
    t_left, t_top, t_right, t_bottom = text
    p_left, p_top, p_right, p_bottom = picture
    overlaps_x = min(t_right, p_right) > max(t_left, p_left)
    overlaps_y = min(t_bottom, p_bottom) > max(t_top, p_top)
    candidates = []
    if overlaps_x and 0 <= t_top - p_bottom <= CAPTION_GAP:
        candidates.append(t_top - p_bottom)
    if overlaps_x and 0 <= p_top - t_bottom <= CAPTION_GAP:
        candidates.append(p_top - t_bottom + ABOVE_PENALTY)
    if overlaps_y and 0 <= t_left - p_right <= CAPTION_GAP:
        candidates.append(t_left - p_right + SIDE_PENALTY)
    if overlaps_y and 0 <= p_left - t_right <= CAPTION_GAP:
        candidates.append(p_left - t_right + SIDE_PENALTY)
    # A label sitting on top of the picture names it too — that is an overlay,
    # the tightest pairing there is. But it has to *start* inside the frame: a
    # text box is left-aligned and often far wider than its words, so one placed
    # flush against a picture's right edge spills over the next picture without
    # naming it. Requiring the left edge to be inside is what keeps a city label
    # on the photo it touches rather than on its neighbour.
    if overlaps_x and overlaps_y and t_left >= p_left:
        candidates.append(0)
    return min(candidates) if candidates else None


def pptx_slide_lines(tree: ElementTree.Element, rels: dict, media: MediaSink,
                     folder: str) -> list[str]:
    """One slide, pictures paired with the captions that name them.

    Reading order on a slide is spatial, and the pairing *picture ↔ caption* is
    carried by nothing else than position: a caption is the text under the
    frame, sharing its left edge. Emitting the two separately, each in its own
    band of the slide, is what loses it — so the pairing is resolved here, once,
    rather than guessed downstream from a flat list.
    """
    titles: list[str] = []
    title_band: list[tuple[int, int]] = []
    pictures: list[tuple[tuple, str]] = []
    texts: list[tuple[tuple, str]] = []
    extra: list[str] = []

    for shape in tree:
        tag = local(shape.tag)
        if tag == "pic":
            for blip in shape.iter(q("a", "blip")):
                target = rels.get(blip.attrib.get(q("r", "embed"), ""))
                if target and not target[1] and (name := media.take(folder, target[0])):
                    pictures.append((shape_box(shape), name))
        elif tag == "graphicFrame":
            for row in shape.iter(q("a", "tr")):
                cells = [" ".join(drawing_text_lines(cell))
                         for cell in row.findall(q("a", "tc"))]
                extra.append("| " + " | ".join(cells) + " |")
        elif tag == "sp":
            if not (lines := drawing_text_lines(shape)):
                continue
            box = shape_box(shape)
            if is_title(shape):
                titles += lines
                title_band.append((box[1], box[3]))
            else:
                texts.append((box, " / ".join(lines)))
        extra += [f"<{url}>" for url in drawing_links(shape, rels)]

    # Each caption goes to the picture it is closest to, and to any other one it
    # is just as close to — a row of frames sharing a single caption.
    captions: dict[int, list[str]] = {}
    notes: list[tuple[tuple, str]] = []
    for box, text in texts:
        # Text sharing the title's line is a statement about the whole slide —
        # a subtitle — and naming whichever frame it happens to sit beside would
        # attach it to a picture it says nothing about.
        beside_title = any(min(box[3], bottom) > max(box[1], top)
                           for top, bottom in title_band)
        costs = [] if beside_title else [
            (cost, index) for index, (picture, _) in enumerate(pictures)
            if (cost := caption_cost(box, picture)) is not None]
        if not costs:
            notes.append((box, text))
            continue
        best = min(cost for cost, _ in costs)
        for cost, index in costs:
            if cost <= best + TIE:
                captions.setdefault(index, []).append(text)

    # Grouped so a caption naming three frames is stated once, not three times.
    grouped: dict[str, list[str]] = {}
    for index, names in captions.items():
        grouped.setdefault(" / ".join(names), []).append(pictures[index][1])

    entries: list[tuple[tuple[int, int], str]] = []
    for text, names in grouped.items():
        first = min(pictures[i][0] for i, _ in enumerate(pictures)
                    if pictures[i][1] in names)
        entries.append(((first[1], first[0]), f"[img: {', '.join(names)}] {text}"))
    for index, (box, name) in enumerate(pictures):
        if index not in captions:
            entries.append(((box[1], box[0]), f"[img: {name}] (no caption)"))
    for box, text in notes:
        entries.append(((box[1], box[0]), text))

    return ([f"### {title}" for title in titles]
            + [line for _, line in sorted(entries, key=lambda entry: entry[0])]
            + extra)


def pptx_lines(archive: zipfile.ZipFile, media: MediaSink) -> list[str]:
    presentation = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
    deck_rels = read_rels(archive, "ppt/presentation.xml")
    lines: list[str] = []
    number = 0
    for node in presentation.iter(q("p", "sldId")):
        target = deck_rels.get(node.attrib.get(q("r", "id"), ""))
        if not target or target[1]:
            continue
        part = posixpath.normpath(posixpath.join("ppt", target[0]))
        if part not in archive.namelist():
            continue
        number += 1
        rels = read_rels(archive, part)
        folder = posixpath.dirname(part)
        slide = ElementTree.fromstring(archive.read(part))
        tree = next(slide.iter(q("p", "spTree")), None)
        if tree is None:
            continue
        lines.append(f"## slide {number}")
        lines += pptx_slide_lines(tree, rels, media, folder)
        # Speaker notes carry the commentary in some decks, and cost nothing.
        for relation, external in rels.values():
            if external or "notesSlide" not in relation:
                continue
            notes_part = posixpath.normpath(posixpath.join(folder, relation))
            if notes_part not in archive.namelist():
                continue
            notes = ElementTree.fromstring(archive.read(notes_part))
            for text in drawing_text_lines(notes):
                if text.strip() != str(number):
                    lines.append(f"> {text}")
    return lines


# --------------------------------------------------------------------------- #
# The other formats
# --------------------------------------------------------------------------- #

def html_lines(path: Path, media_dir: Path) -> list[str]:
    from selectolax.lexbor import LexborHTMLParser

    tree = LexborHTMLParser(path.read_text("utf-8", errors="replace"))
    for node in tree.css("script, style, noscript"):
        node.decompose()
    lines: list[str] = []
    for node in tree.css("h1, h2, h3, h4, p, li, td, th, img, a[href]"):
        if node.tag == "img":
            source = node.attributes.get("src") or ""
            # A browser writes the src percent-encoded, and the folder it saved
            # alongside is named after the page — so any page whose title holds a
            # space arrives as `My%20Page_files/…`. Without decoding, every one of
            # its images silently misses on disk.
            local = urllib.parse.unquote(source.split("?")[0].split("#")[0])
            name = posixpath.basename(local)
            candidate = (path.parent / local).resolve()
            alt = (node.attributes.get("alt") or "").strip()
            # Alt text is the caption analogue on a web page: worth carrying.
            suffix = f" (alt: {alt})" if alt else ""
            if source.startswith(("http", "data:")):
                lines.append(f"[img-remote: {source[:120]}]{suffix}")
            elif not source:
                pass
            elif candidate.exists():
                media_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(candidate, media_dir / name)
                lines.append(f"[img: {name}]{suffix}")
            else:
                # Said out loud rather than dropped: a miss here means the saved
                # folder is gone or renamed, which is worth knowing about.
                lines.append(f"[img-missing: {name}]{suffix}")
            continue
        if node.tag == "a":
            href = node.attributes.get("href") or ""
            if "google" in href and "map" in href:
                lines.append(f"<{href}>")
            continue
        if (text := (node.text(deep=True) or "").strip()):
            prefix = "#" * int(node.tag[1]) + " " if node.tag in ("h1", "h2", "h3", "h4") else ""
            lines.append(prefix + " ".join(text.split()))
    return lines


def json_lines(path: Path) -> list[str]:
    payload = json.loads(path.read_text("utf-8"))
    header = []
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        keys = sorted({key for item in payload if isinstance(item, dict) for key in item})
        header = [f"## list of {len(payload)} objects", f"keys: {', '.join(keys)}"]
    return header + json.dumps(payload, ensure_ascii=False, indent=1).splitlines()


def pdf_lines(path: Path, media_dir: Path) -> list[str]:
    try:
        import pymupdf  # type: ignore
    except ImportError:
        raise SystemExit(
            "PDF needs pymupdf, which is not a project dependency.\n"
            "Install it just for this: uv add --group dev pymupdf"
        ) from None
    lines: list[str] = []
    with pymupdf.open(path) as document:
        for number, page in enumerate(document, start=1):
            lines.append(f"## page {number}")
            for image in page.get_images(full=True):
                xref = image[0]
                extracted = document.extract_image(xref)
                name = f"page{number:03d}-x{xref}.{extracted['ext']}"
                media_dir.mkdir(parents=True, exist_ok=True)
                (media_dir / name).write_bytes(extracted["image"])
                lines.append(f"[img: {name}]")
            lines += [" ".join(line.split())
                      for line in page.get_text().splitlines() if line.strip()]
    return lines


# --------------------------------------------------------------------------- #

def sources() -> list[Path]:
    """The numbered candidates: files directly in input/to_parse, sorted."""
    if not TO_PARSE.exists():
        return []
    return sorted((p for p in TO_PARSE.iterdir() if p.is_file()),
                  key=lambda p: p.name.lower())


def resolve(target: str) -> Path:
    if target.isdigit():
        files = sources()
        index = int(target)
        if not 1 <= index <= len(files):
            raise SystemExit(
                f"no. {index} out of range: {len(files)} file(s) in {TO_PARSE}.\n"
                "Run with --list to see the numbering."
            )
        return files[index - 1]
    path = Path(target)
    if not path.exists():
        raise SystemExit(f"file not found: {path}")
    return path


def transcribe(path: Path, out_dir: Path) -> list[str]:
    media_dir = out_dir / "media"
    suffix = path.suffix.lower()
    if suffix in (".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"):
        readers = {"doc": docx_lines, "xls": xlsx_lines, "ppt": pptx_lines}
        with zipfile.ZipFile(path) as archive:
            return readers[suffix[1:4]](archive, MediaSink(archive, media_dir))
    if suffix in (".htm", ".html"):
        return html_lines(path, media_dir)
    if suffix == ".json":
        return json_lines(path)
    if suffix == ".pdf":
        return pdf_lines(path, media_dir)
    if suffix in (".txt", ".md"):
        return path.read_text("utf-8", errors="replace").splitlines()
    raise SystemExit(f"unsupported format: {suffix or path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?",
                        help="a no. from --list, or a path to a document")
    parser.add_argument("--list", action="store_true",
                        help="number the files of input/to_parse and exit")
    arguments = parser.parse_args()

    if arguments.list or not arguments.target:
        files = sources()
        if not files:
            print(f"{TO_PARSE} holds no file.")
            return
        for index, path in enumerate(files, start=1):
            print(f"{index:>3}. {path.name}  ({path.stat().st_size / 1024:.0f} KB)")
        return

    path = resolve(arguments.target)
    out_dir = STAGED / slugify(path.stem)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    lines = transcribe(path, out_dir)
    # Runs of blank lines carry nothing and cost tokens to read.
    cleaned: list[str] = []
    for line in lines:
        if line.strip() or (cleaned and cleaned[-1].strip()):
            cleaned.append(line.rstrip())
    transcript = out_dir / "transcript.md"
    transcript.write_text(f"# {path.name}\n\n" + "\n".join(cleaned).strip() + "\n", "utf-8")

    images = sorted((out_dir / "media").glob("*")) if (out_dir / "media").exists() else []
    print(f"{path.name}")
    print(f"  transcript : {transcript.as_posix()}  "
          f"({len(cleaned)} lines, {transcript.stat().st_size / 1024:.0f} KB)")
    print(f"  media      : {len(images)} image(s) in {(out_dir / 'media').as_posix()}")


if __name__ == "__main__":
    main()
