from __future__ import annotations

import io
from io import BytesIO
from pathlib import Path

from PIL import Image

from cartometa.build.assets import write_hashed
from cartometa.build.image_cache import ImageCache, cle_de

# La galerie affiche les vignettes autour de 300 px de large ; 600 couvre les
# écrans à densité double sans gaspiller.
THUMB_WIDTH = 600
# Plancher, pas confort : ce sont des montages à plusieurs panneaux annotés,
# illisibles en dessous.
FULL_WIDTH = 1400
QUALITY = 78

# Entre dans la clé du cache : toute évolution des réglages d'encodage, ou de
# l'encodeur lui-même, doit rendre les entrées existantes inutilisables plutôt
# que de servir des images produites selon des réglages abandonnés.
SIGNATURE = f"v1-lanczos-{THUMB_WIDTH}-{FULL_WIDTH}-q{QUALITY}"


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


def render_image_pair(
    source: Path, out_dir: Path, stem: str, cache: ImageCache | None = None
) -> dict[str, str]:
    """Produit la vignette et la pleine taille, et renvoie leurs deux noms.

    Avec un `cache`, l'encodage — de loin la partie coûteuse — n'a lieu que
    la première fois qu'une image source est rencontrée.
    """
    if not source.exists():
        raise MissingImageError(f"image introuvable : {source}")
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
