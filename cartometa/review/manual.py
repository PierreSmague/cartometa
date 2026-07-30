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

# Une capture d'écran collée dépasse rarement le mégaoctet. Le plafond
# n'existe pas pour contraindre l'usage mais pour qu'un client incorrect ne
# puisse pas remplir le disque.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

EXTENSION_BY_FORMAT = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}

CATEGORIES = ("bollards", "poteaux", "vehicule", "vegetation", "signalisation", "autre")

# Forme exacte d'un identifiant frappé par `new_meta_id` : un préfixe fixe
# suivi de quatre caractères hexadécimaux, rien d'autre.
_MINTED_ID = re.compile(r"^man-[0-9a-f]{4}$")


class ManualMetaError(ValueError):
    """Saisie manuelle refusée : champ manquant, ou image inexploitable."""


def new_meta_id(existing: set[str]) -> str:
    """Identifiant `man-xxxx` libre.

    Le préfixe rend toute collision impossible avec les identifiants Plonk
    It, qui font quatre caractères sans préfixe.
    """
    while True:
        candidate = f"man-{secrets.token_hex(2)}"
        if candidate not in existing:
            return candidate


def _required(value: str | None, label: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ManualMetaError(f"{label} est obligatoire")
    return cleaned


def create_meta(
    paths: CountryPaths,
    *,
    title: str | None,
    description: str | None,
    category: str | None,
    source_url: str | None = "",
) -> dict:
    """Crée une méta saisie à la main et l'ajoute au fichier manuel du pays."""
    title = _required(title, "le titre")
    description = _required(description, "la description")
    if category not in CATEGORIES:
        raise ManualMetaError(
            f"catégorie inconnue : {category!r} (attendu {', '.join(CATEGORIES)})"
        )

    meta = MetaRecord(
        # L'unicité se juge sur les DEUX sources : un identifiant libre côté
        # manuel mais déjà pris côté import casserait la fusion.
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
    """Chemin tel que le serveur le sert : relatif à la racine du projet.

    Le serveur sert les fichiers depuis son répertoire de travail, et les
    métas importées y stockent déjà `input/…`. On garde la même convention
    pour que l'interface n'ait qu'une règle : préfixer par `/`.
    """
    root = Path.cwd().resolve()
    absolute = (root / path).resolve()
    if absolute.is_relative_to(root):
        return absolute.relative_to(root).as_posix()
    return absolute.as_posix()


def save_image(paths: CountryPaths, meta_id: str, raw: bytes) -> str:
    """Écrit l'image d'une méta manuelle et la rattache à celle-ci."""
    # Validé avant toute construction de chemin et avant la recherche dans
    # metas.json : le garde-fou ne doit pas dépendre du contenu du fichier,
    # seulement de la forme de l'identifiant lui-même.
    if Path(meta_id).name != meta_id or not _MINTED_ID.fullmatch(meta_id):
        raise ManualMetaError(f"identifiant de méta invalide : {meta_id!r}")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ManualMetaError(
            f"image trop lourde : {len(raw)} octets, maximum {MAX_IMAGE_BYTES}"
        )
    try:
        image = Image.open(BytesIO(raw))
        image_format = image.format
        image.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ManualMetaError("les octets reçus ne forment pas une image lisible") from None
    except DecompressionBombError:
        raise ManualMetaError("l'image déclare des dimensions trop grandes pour être traitées") from None
    extension = EXTENSION_BY_FORMAT.get(image_format or "")
    if extension is None:
        raise ManualMetaError(f"format d'image non accepté : {image_format!r}")

    metas = read_json_list(paths.manual_metas)
    target = next((m for m in metas if m["id"] == meta_id), None)
    if target is None:
        raise ManualMetaError(f"méta manuelle inconnue : {meta_id!r}")

    # Le nom du fichier vient de l'identifiant reçu, mais celui-ci a déjà été
    # validé contre la forme mintée (`man-` + 4 hex, sans composant de
    # chemin) puis retrouvé dans metas.json : aucun composant de chemin
    # fourni par le client ne peut donc atteindre le système de fichiers.
    paths.manual_images.mkdir(parents=True, exist_ok=True)
    destination = paths.manual_images / f"{meta_id}{extension}"
    destination.write_bytes(raw)

    target["image"] = _relative_to_cwd(destination)
    write_json_atomic(paths.manual_metas, metas)
    return target["image"]
