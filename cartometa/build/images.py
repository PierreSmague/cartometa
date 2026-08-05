from __future__ import annotations

import io
from io import BytesIO
from pathlib import Path

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


class MissingImageError(FileNotFoundError):
    """Raised when a meta references an image that is missing from disk."""


def _encode(image: Image.Image, largeur: int) -> bytes:
    copie = image.copy()
    # `thumbnail` only ever shrinks: a source smaller than the target is left
    # as-is, never upscaled.
    copie.thumbnail((largeur, largeur * 10), Image.LANCZOS)
    tampon = io.BytesIO()
    copie.save(tampon, "WEBP", quality=QUALITY, method=4)
    return tampon.getvalue()


def render_image_pair(
    source: Path, out_dir: Path, stem: str, cache: ImageCache | None = None
) -> dict[str, str]:
    """Produce the thumbnail and the full size, and return both their names.

    With a `cache`, the encoding — by far the expensive part — only happens the
    first time a source image is encountered.
    """
    if not source.exists():
        raise MissingImageError(f"image not found: {source}")
    octets = source.read_bytes()
    cle = cle_de(octets, SIGNATURE) if cache is not None else ""
    vignette = cache.lire(cle, "t") if cache is not None else None
    pleine = cache.lire(cle, "f") if cache is not None else None
    if vignette is None or pleine is None:
        with Image.open(BytesIO(octets)) as image:
            image = image.convert("RGB")
            vignette = _encode(image, THUMB_WIDTH)
            pleine = _encode(image, FULL_WIDTH)
        if cache is not None:
            cache.ecrire(cle, "t", vignette)
            cache.ecrire(cle, "f", pleine)
    return {
        "thumb": write_hashed(out_dir, f"{stem}.t", ".webp", vignette),
        "full": write_hashed(out_dir, f"{stem}.f", ".webp", pleine),
    }
