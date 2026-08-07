from __future__ import annotations

import io
from io import BytesIO
from pathlib import Path

import resvg_py
from PIL import Image

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
