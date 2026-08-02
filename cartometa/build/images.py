from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from cartometa.build.assets import write_hashed

# La galerie affiche les vignettes autour de 300 px de large ; 600 couvre les
# écrans à densité double sans gaspiller.
THUMB_WIDTH = 600
# Plancher, pas confort : ce sont des montages à plusieurs panneaux annotés,
# illisibles en dessous.
FULL_WIDTH = 1400
QUALITY = 78


class MissingImageError(FileNotFoundError):
    """Levée quand une méta référence une image absente du disque."""


def _encode(image: Image.Image, largeur: int) -> bytes:
    copie = image.copy()
    # `thumbnail` ne fait que réduire : une source plus petite que la cible
    # est laissée telle quelle, jamais interpolée vers le haut.
    copie.thumbnail((largeur, largeur * 10), Image.LANCZOS)
    tampon = io.BytesIO()
    copie.save(tampon, "WEBP", quality=QUALITY, method=4)
    return tampon.getvalue()


def render_image_pair(source: Path, out_dir: Path, stem: str) -> dict[str, str]:
    """Produit la vignette et la pleine taille, et renvoie leurs deux noms."""
    if not source.exists():
        raise MissingImageError(f"image introuvable : {source}")
    with Image.open(source) as image:
        image = image.convert("RGB")
        vignette = _encode(image, THUMB_WIDTH)
        pleine = _encode(image, FULL_WIDTH)
    return {
        "thumb": write_hashed(out_dir, f"{stem}.t", ".webp", vignette),
        "full": write_hashed(out_dir, f"{stem}.f", ".webp", pleine),
    }
