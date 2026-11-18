from __future__ import annotations

import io
from io import BytesIO
from pathlib import Path

import resvg_py
from PIL import Image, ImageDraw, ImageFont

from cartometa.build.assets import write_hashed
from cartometa.build.image_cache import ImageCache, cle_de

# The gallery shows thumbnails around 300 px wide; 600 covers double-density
# screens without waste.
THUMB_WIDTH = 600
# A floor, not comfort: these are multi-panel annotated montages, unreadable
# below that.
FULL_WIDTH = 1400
QUALITY = 78

# Part of the cache key: any change to the encoding settings, or to the encoder
# itself, has to make existing entries unusable rather than serve images produced
# according to abandoned settings.
SIGNATURE = f"v1-lanczos-{THUMB_WIDTH}-{FULL_WIDTH}-q{QUALITY}"
# Compositing settings for the RMRG trace (bottom-right, contain-fit in a
# 1/3 x 1/3 box). Only mixed into the key when a trace is present: the
# overlay-less entries, unchanged by this feature, keep their cache.
OVERLAY_SIGNATURE = "ov1-ninth-bottom-right"


class MissingImageError(FileNotFoundError):
    """Raised when a meta references an image that is missing from disk."""


def _incruster(image: Image.Image, overlay_svg: str) -> None:
    """Composite the trace bottom-right, contain-fit in a W/3 x H/3 box.

    Rasterized from the vector source at the exact target size — once per
    output size, so the strokes stay crisp on the thumbnail as well as on the
    full image, instead of being downscaled from a single raster.
    """
    boite_l, boite_h = image.width // 3, image.height // 3
    trace = Image.open(BytesIO(bytes(
        resvg_py.svg_to_bytes(svg_string=overlay_svg, width=boite_l)
    )))
    if trace.height > boite_h:
        trace = Image.open(BytesIO(bytes(
            resvg_py.svg_to_bytes(svg_string=overlay_svg, height=boite_h)
        )))
    if trace.mode != "RGBA":
        trace = trace.convert("RGBA")
    # The alpha channel as mask: the mini-maps are transparent outside the
    # country outline, and the photo has to keep showing through there.
    image.paste(
        trace, (image.width - trace.width, image.height - trace.height), trace
    )


def _encode(image: Image.Image, largeur: int, overlay_svg: str | None = None) -> bytes:
    copie = image.copy()
    # `thumbnail` only ever shrinks: a source smaller than the target is left
    # as-is, never upscaled.
    copie.thumbnail((largeur, largeur * 10), Image.LANCZOS)
    if overlay_svg is not None:
        _incruster(copie, overlay_svg)
    tampon = io.BytesIO()
    copie.save(tampon, "WEBP", quality=QUALITY, method=4)
    return tampon.getvalue()


def render_image_pair(
    source: Path,
    out_dir: Path,
    stem: str,
    cache: ImageCache | None = None,
    overlay: Path | None = None,
) -> dict[str, str]:
    """Produce the thumbnail and the full size, and return both their names.

    With an `overlay` (RMRG only: the guide's region mini-map, SVG), the trace
    is baked into both outputs, bottom-right. With a `cache`, the encoding — by
    far the expensive part — only happens the first time a source image is
    encountered.
    """
    if not source.exists():
        raise MissingImageError(f"image not found: {source}")
    if overlay is not None and not overlay.exists():
        raise MissingImageError(f"overlay not found: {overlay}")
    octets = source.read_bytes()
    overlay_svg: str | None = None
    if overlay is not None:
        octets_overlay = overlay.read_bytes()
        overlay_svg = octets_overlay.decode("utf-8")
        # The trace bytes join the key: the same photo with and without trace
        # (or with a corrected trace) must never share a cache entry.
        empreinte_source = octets + b"\0" + octets_overlay
        signature = f"{SIGNATURE}-{OVERLAY_SIGNATURE}"
    else:
        empreinte_source = octets
        signature = SIGNATURE
    cle = cle_de(empreinte_source, signature) if cache is not None else ""
    vignette = cache.lire(cle, "t") if cache is not None else None
    pleine = cache.lire(cle, "f") if cache is not None else None
    if vignette is None or pleine is None:
        with Image.open(BytesIO(octets)) as image:
            image = image.convert("RGB")
            vignette = _encode(image, THUMB_WIDTH, overlay_svg)
            pleine = _encode(image, FULL_WIDTH, overlay_svg)
        if cache is not None:
            cache.ecrire(cle, "t", vignette)
            cache.ecrire(cle, "f", pleine)
    return {
        "thumb": write_hashed(out_dir, f"{stem}.t", ".webp", vignette),
        "full": write_hashed(out_dir, f"{stem}.f", ".webp", pleine),
    }


# --- Tiles: the image of a meta that has none --------------------------------
#
# carmeta metas come with no screenshot. Their image is a flat tile in the
# colour their tag has on the carmeta maps — the colour of the car, which is how
# players know these coverages — carrying the title. A real image rather than a
# styled block in the page: the gallery, the blow-up, the Anki cards and the
# userscript all consume `thumb`/`full` and need no special case.
TILE_RATIO = 2            # width / height, the gallery's 16:8 box
TILE_FALLBACK = "#ffffff"
TILE_DARK_TEXT = "#000000"
TILE_LIGHT_TEXT = "#ffffff"
# Share of the width the text may occupy, and text sizes as shares of the width.
TILE_TEXT_WIDTH = 0.86
TILE_LABEL_SIZE = 0.082
TILE_YEAR_SIZE = 0.15
TILE_SINGLE_SIZE = 0.105
# A title reads "<what> · <year>": the year gets its own, larger line.
_SEPARATOR = " · "


def _channels(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def tile_text_colour(colour: str) -> str:
    """White text, or dark text when the car is white or gray.

    "Gray" is any colour without hue that is not close to black: a black car
    keeps white text. Very light tints (pale green, pale blue) get dark text
    too — white on them would simply not be readable.
    """
    red, green, blue = _channels(colour)
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    achromatic = max(red, green, blue) - min(red, green, blue) <= 24
    if (achromatic and luminance >= 80) or luminance >= 170:
        return TILE_DARK_TEXT
    return TILE_LIGHT_TEXT


def _wrapped(draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        candidate = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textlength(candidate, font=font) <= max_width:
            lines[-1] = candidate
        elif not lines and draw.textlength(candidate, font=font) <= max_width:
            lines.append(candidate)
        else:
            lines.append(word)
    return lines or [""]


def _tile(title: str, colour: str, width: int) -> bytes:
    height = width // TILE_RATIO
    image = Image.new("RGB", (width, height), colour)
    draw = ImageDraw.Draw(image)
    ink = tile_text_colour(colour)
    label, _, year = title.partition(_SEPARATOR)
    # Pillow's bundled font: no font file to ship, the same glyphs on every machine.
    if year:
        blocks = [(ImageFont.load_default(size=width * TILE_LABEL_SIZE), label),
                  (ImageFont.load_default(size=width * TILE_YEAR_SIZE), year)]
    else:
        blocks = [(ImageFont.load_default(size=width * TILE_SINGLE_SIZE), label)]
    rows = []        # (text, font, line height)
    for font, text in blocks:
        ascent, descent = font.getmetrics()
        for line in _wrapped(draw, text, font, width * TILE_TEXT_WIDTH):
            rows.append((line, font, (ascent + descent) * 1.08))
    y = (height - sum(row[2] for row in rows)) / 2
    for line, font, line_height in rows:
        draw.text((width / 2, y + line_height / 2), line, font=font, fill=ink, anchor="mm")
        y += line_height
    if colour.lower() == TILE_FALLBACK:
        # A white tile on a white page has no edge of its own.
        draw.rectangle((0, 0, width - 1, height - 1), outline="#e7e7e3",
                       width=max(1, width // 300))
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=QUALITY, method=4)
    return buffer.getvalue()


def render_tile_pair(title: str, colour: str | None, out_dir: Path, stem: str) -> dict[str, str]:
    """Thumbnail and full size of a meta with no image: its title on its colour.

    `colour` is `#rrggbb`, or None — a white tile then, as for a white car.
    """
    colour = colour or TILE_FALLBACK
    return {
        "thumb": write_hashed(out_dir, f"{stem}.t", ".webp", _tile(title, colour, THUMB_WIDTH)),
        "full": write_hashed(out_dir, f"{stem}.f", ".webp", _tile(title, colour, FULL_WIDTH)),
    }
