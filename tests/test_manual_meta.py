import json
import struct
import zlib
from io import BytesIO

import pytest
from PIL import Image

from cartometa.review.manual import (
    MAX_IMAGE_BYTES,
    ManualMetaError,
    create_meta,
    new_meta_id,
    save_image,
)
from cartometa.review.store import CountryPaths, load_metas, read_json_list


def _png(size=(40, 30), color=(200, 30, 30)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _decompression_bomb_png() -> bytes:
    """Crée un PNG qui declare des dimensions 60000x60000 avec donnees comprimees minimales.

    PIL refuse de traiter cette image car elle declare trop de pixels (decompression bomb).
    Cela leve PIL.Image.DecompressionBombError, pas UnidentifiedImageError.
    """
    png_data = b'\x89PNG\r\n\x1a\n'

    # IHDR chunk with huge dimensions
    width = 60000
    height = 60000
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
    png_data += struct.pack('>I', len(ihdr_data))
    png_data += b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)

    # Minimal IDAT chunk
    compressed = zlib.compress(b'\x00' * (width * height * 3))[:100]
    idat_crc = zlib.crc32(b'IDAT' + compressed) & 0xffffffff
    png_data += struct.pack('>I', len(compressed))
    png_data += b'IDAT' + compressed + struct.pack('>I', idat_crc)

    # IEND chunk
    iend_crc = zlib.crc32(b'IEND') & 0xffffffff
    png_data += struct.pack('>I', 0)
    png_data += b'IEND' + struct.pack('>I', iend_crc)

    return png_data


@pytest.fixture
def paths(tmp_path):
    return CountryPaths(tmp_path / "data", "PL")


def _create(paths, **extra):
    champs = {"title": "Bornes jaunes", "description": "Les bornes sont jaunes.",
              "category": "bollards"}
    champs.update(extra)
    return create_meta(paths, **champs)


def test_l_identifiant_est_prefixe(paths):
    meta = _create(paths)

    assert meta["id"].startswith("man-")
    assert len(meta["id"]) == len("man-") + 4


def test_la_meta_est_ecrite_dans_le_fichier_manuel(paths):
    meta = _create(paths)

    enregistrees = read_json_list(paths.manual_metas)
    assert [m["id"] for m in enregistrees] == [meta["id"]]


def test_la_meta_porte_l_origine_manuelle(paths):
    meta = _create(paths)

    assert meta["origin"] == "manual"
    assert meta["tier"] == "manual"
    assert meta["country"] == "PL"


def test_les_metas_s_accumulent(paths):
    _create(paths, title="Une")
    _create(paths, title="Deux")

    assert len(read_json_list(paths.manual_metas)) == 2


def test_identifiant_unique_meme_en_cas_de_collision(monkeypatch):
    tirages = iter(["abcd", "abcd", "ef01"])
    monkeypatch.setattr(
        "cartometa.review.manual.secrets.token_hex", lambda _n: next(tirages)
    )

    assert new_meta_id({"man-abcd"}) == "man-ef01"


def test_titre_vide_refuse(paths):
    with pytest.raises(ManualMetaError):
        _create(paths, title="   ")


def test_description_vide_refusee(paths):
    with pytest.raises(ManualMetaError):
        _create(paths, description="")


def test_categorie_inconnue_refusee(paths):
    with pytest.raises(ManualMetaError):
        _create(paths, category="licornes")


def test_l_image_est_ecrite_sous_un_nom_genere(paths):
    meta = _create(paths)

    save_image(paths, meta["id"], _png())

    assert (paths.manual_images / f"{meta['id']}.png").exists()


def test_l_image_est_rattachee_a_la_meta(paths):
    meta = _create(paths)

    save_image(paths, meta["id"], _png())

    relu = next(m for m in load_metas(paths) if m["id"] == meta["id"])
    assert relu["image"].endswith(f"{meta['id']}.png")


def test_le_format_jpeg_est_accepte(paths):
    meta = _create(paths)
    buffer = BytesIO()
    Image.new("RGB", (10, 10), (0, 0, 0)).save(buffer, format="JPEG")

    save_image(paths, meta["id"], buffer.getvalue())

    assert (paths.manual_images / f"{meta['id']}.jpg").exists()


def test_octets_qui_ne_sont_pas_une_image_refuses(paths):
    meta = _create(paths)

    with pytest.raises(ManualMetaError):
        save_image(paths, meta["id"], b"<?php system($_GET['c']); ?>")


def test_image_trop_lourde_refusee(paths):
    meta = _create(paths)

    with pytest.raises(ManualMetaError):
        save_image(paths, meta["id"], b"\x89PNG" + b"\x00" * MAX_IMAGE_BYTES)


def test_bombe_decompression_refusee(paths):
    """Regression: une bombe de decompression (PNG avec dimensions declarees enormes) leve DecompressionBombError.

    Ce n'est pas UnidentifiedImageError ni OSError ni ValueError, donc sans gestion specifique,
    l'exception s'echapperait non-convertie en ManualMetaError.
    """
    meta = _create(paths)

    with pytest.raises(ManualMetaError):
        save_image(paths, meta["id"], _decompression_bomb_png())


def test_image_pour_une_meta_inconnue_refusee(paths):
    _create(paths)

    with pytest.raises(ManualMetaError):
        save_image(paths, "man-ffff", _png())


def test_aucun_fichier_n_est_ecrit_hors_du_dossier_images(paths):
    """Le nom du fichier vient de l'identifiant serveur, jamais du client."""
    meta = _create(paths)

    save_image(paths, meta["id"], _png())

    ecrits = list(paths.manual_images.iterdir())
    assert [p.name for p in ecrits] == [f"{meta['id']}.png"]
