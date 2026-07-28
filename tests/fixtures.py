from __future__ import annotations
import numpy as np
from PIL import Image, ImageDraw

CREAM = (255, 253, 235, 255)
RED = (193, 40, 58, 255)


def synthetic_meta_image(
    size: tuple[int, int] = (1920, 943),
    with_inset: bool = True,
    red_shape: str | None = "zone",
    parasite_red: bool = True,
) -> Image.Image:
    """Reproduit le template Plonk It mesuré.

    red_shape: "zone" (ellipse dans la silhouette), "pin" (petit blob), None.
    """
    w, h = size
    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # Photo a gauche : bruit opaque, avec du rouge parasite façon rose des vents.
    photo_w = int(w * 0.872)
    rng = np.random.default_rng(0)
    noise = rng.integers(60, 200, size=(h, photo_w, 3), dtype=np.uint8)
    alpha = np.full((h, photo_w, 1), 255, dtype=np.uint8)
    img.paste(Image.fromarray(np.concatenate([noise, alpha], axis=2), "RGBA"), (0, 0))
    if parasite_red:
        draw.ellipse([60, h - 200, 200, h - 60], fill=RED)

    if not with_inset:
        return img

    # Encart : silhouette crème rectangulaire aux coordonnées relatives mesurées.
    x0, x1 = int(w * 0.719), int(w * 0.994)
    y0, y1 = int(h * 0.464), int(h * 0.987)
    draw.rectangle([x0, y0, x1, y1], fill=CREAM)

    if red_shape == "zone":
        draw.ellipse(
            [x0 + (x1 - x0) // 4, y0 + (y1 - y0) // 2, x0 + (x1 - x0) // 2, y1 - 20],
            fill=RED,
        )
    elif red_shape == "pin":
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        draw.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=RED)
    return img
