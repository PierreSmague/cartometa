from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from PIL.Image import DecompressionBombError

from cartometa.atomic_write import write_json_atomic
from cartometa.models import ORIGIN_MANUAL, TIER_MANUAL, MetaRecord
from cartometa.review.store import CountryPaths, load_metas, read_json_list

# A pasted screenshot rarely goes beyond a megabyte. The cap does not exist to
# constrain usage but so that a misbehaving client cannot fill the disk.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

EXTENSION_BY_FORMAT = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}

CATEGORIES = ("bollards", "poteaux", "vehicule", "vegetation", "signalisation", "autre")

# Exact shape of an identifier minted by `new_meta_id`: a fixed prefix followed
# by four hexadecimal characters, nothing else.
_MINTED_ID = re.compile(r"^man-[0-9a-f]{4}$")


class ManualMetaError(ValueError):
    """Manual entry refused: missing field, or unusable image."""


def new_meta_id(existing: set[str]) -> str:
    """A free `man-xxxx` identifier.

    The prefix makes any collision with Plonk It identifiers impossible, as those
    are four characters with no prefix.
    """
    while True:
        candidate = f"man-{secrets.token_hex(2)}"
        if candidate not in existing:
            return candidate


def _required(value: str | None, label: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ManualMetaError(f"{label} is required")
    return cleaned


def create_meta(
    paths: CountryPaths,
    *,
    title: str | None,
    description: str | None,
    category: str | None,
    source_url: str | None = "",
) -> dict:
    """Create a hand-entered meta and append it to the country's manual file."""
    title = _required(title, "the title")
    description = _required(description, "the description")
    if category not in CATEGORIES:
        raise ManualMetaError(
            f"unknown category: {category!r} (expected {', '.join(CATEGORIES)})"
        )

    meta = MetaRecord(
        # Uniqueness is judged over BOTH sources: an identifier free on the manual
        # side but already taken on the imported side would break the merge.
        id=new_meta_id({m["id"] for m in load_metas(paths)}),
        country=paths.country,
        tier=TIER_MANUAL,
        title=title,
        description=description,
        category=category,
        source_url=(source_url or "").strip(),
        extracted_at=datetime.now(timezone.utc).isoformat(),
        description_origin="manual",
        origin=ORIGIN_MANUAL,
    ).to_dict()

    existing = read_json_list(paths.manual_metas)
    existing.append(meta)
    write_json_atomic(paths.manual_metas, existing)
    return meta


def _relative_to_cwd(path: Path) -> str:
    """Path as the server serves it: relative to the project root.

    The server serves files from its working directory, and imported metas already
    store `input/…` there. We keep the same convention so the interface has only one
    rule: prefix with `/`.
    """
    root = Path.cwd().resolve()
    absolute = (root / path).resolve()
    if absolute.is_relative_to(root):
        return absolute.relative_to(root).as_posix()
    return absolute.as_posix()


def save_image(paths: CountryPaths, meta_id: str, raw: bytes) -> str:
    """Write a manual meta's image and attach it to that meta."""
    # Validated before any path is built and before the lookup in metas.json: the
    # safety rail must not depend on the file's content, only on the shape of the
    # identifier itself.
    if Path(meta_id).name != meta_id or not _MINTED_ID.fullmatch(meta_id):
        raise ManualMetaError(f"invalid meta identifier: {meta_id!r}")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ManualMetaError(
            f"image too large: {len(raw)} bytes, maximum {MAX_IMAGE_BYTES}"
        )
    try:
        image = Image.open(BytesIO(raw))
        image_format = image.format
        image.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ManualMetaError("the bytes received do not form a readable image") from None
    except DecompressionBombError:
        raise ManualMetaError("the image declares dimensions too large to be processed") from None
    extension = EXTENSION_BY_FORMAT.get(image_format or "")
    if extension is None:
        raise ManualMetaError(f"image format not accepted: {image_format!r}")

    metas = read_json_list(paths.manual_metas)
    target = next((m for m in metas if m["id"] == meta_id), None)
    if target is None:
        raise ManualMetaError(f"unknown manual meta: {meta_id!r}")

    # The file name comes from the identifier received, but that identifier has
    # already been validated against the minted shape (`man-` + 4 hex, no path
    # component) then found in metas.json: so no client-supplied path component can
    # reach the file system.
    paths.manual_images.mkdir(parents=True, exist_ok=True)
    destination = paths.manual_images / f"{meta_id}{extension}"
    destination.write_bytes(raw)

    target["image"] = _relative_to_cwd(destination)
    write_json_atomic(paths.manual_metas, metas)
    return target["image"]
