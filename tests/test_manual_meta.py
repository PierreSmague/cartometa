import struct
import zlib
from io import BytesIO

import pytest
from PIL import Image

from cartometa.atomic_write import write_json_atomic
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
    """Build a PNG declaring 60000x60000 dimensions with minimal compressed data.

    PIL refuses to process this image because it declares too many pixels (a decompression
    bomb). That raises PIL.Image.DecompressionBombError, not UnidentifiedImageError.
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


def test_the_identifier_is_prefixed(paths):
    meta = _create(paths)

    assert meta["id"].startswith("man-")
    assert len(meta["id"]) == len("man-") + 4


def test_the_meta_is_written_into_the_manual_file(paths):
    meta = _create(paths)

    enregistrees = read_json_list(paths.manual_metas)
    assert [m["id"] for m in enregistrees] == [meta["id"]]


def test_the_meta_carries_the_manual_origin(paths):
    meta = _create(paths)

    assert meta["origin"] == "manual"
    assert meta["tier"] == "manual"
    assert meta["country"] == "PL"


def test_the_metas_accumulate(paths):
    _create(paths, title="Une")
    _create(paths, title="Deux")

    assert len(read_json_list(paths.manual_metas)) == 2


def test_unique_identifier_even_on_collision(monkeypatch):
    tirages = iter(["abcd", "abcd", "ef01"])
    monkeypatch.setattr(
        "cartometa.review.manual.secrets.token_hex", lambda _n: next(tirages)
    )

    assert new_meta_id({"man-abcd"}) == "man-ef01"


def test_an_empty_title_is_refused(paths):
    with pytest.raises(ManualMetaError):
        _create(paths, title="   ")


def test_an_empty_description_is_refused(paths):
    with pytest.raises(ManualMetaError):
        _create(paths, description="")


def test_an_unknown_category_is_refused(paths):
    with pytest.raises(ManualMetaError):
        _create(paths, category="licornes")


def test_the_image_is_written_under_a_generated_name(paths):
    meta = _create(paths)

    save_image(paths, meta["id"], _png())

    assert (paths.manual_images / f"{meta['id']}.png").exists()


def test_the_image_is_attached_to_the_meta(paths):
    meta = _create(paths)

    save_image(paths, meta["id"], _png())

    relu = next(m for m in load_metas(paths) if m["id"] == meta["id"])
    assert relu["image"].endswith(f"{meta['id']}.png")


def test_the_jpeg_format_is_accepted(paths):
    meta = _create(paths)
    buffer = BytesIO()
    Image.new("RGB", (10, 10), (0, 0, 0)).save(buffer, format="JPEG")

    save_image(paths, meta["id"], buffer.getvalue())

    assert (paths.manual_images / f"{meta['id']}.jpg").exists()


def test_bytes_that_are_not_an_image_are_refused(paths):
    meta = _create(paths)

    with pytest.raises(ManualMetaError):
        save_image(paths, meta["id"], b"<?php system($_GET['c']); ?>")


def test_an_oversized_image_is_refused(paths):
    meta = _create(paths)

    with pytest.raises(ManualMetaError):
        save_image(paths, meta["id"], b"\x89PNG" + b"\x00" * MAX_IMAGE_BYTES)


def test_a_decompression_bomb_is_refused(paths):
    """Regression: a decompression bomb (a PNG with huge declared dimensions) raises
    DecompressionBombError.

    That is neither UnidentifiedImageError nor OSError nor ValueError, so without specific
    handling the exception would escape unconverted into a ManualMetaError.
    """
    meta = _create(paths)

    with pytest.raises(ManualMetaError):
        save_image(paths, meta["id"], _decompression_bomb_png())


def test_an_image_for_an_unknown_meta_is_refused(paths):
    _create(paths)

    with pytest.raises(ManualMetaError):
        save_image(paths, "man-ffff", _png())


def test_no_file_is_written_outside_the_images_folder(paths):
    """The file name comes from the server-side identifier, never from the client."""
    meta = _create(paths)

    save_image(paths, meta["id"], _png())

    ecrits = list(paths.manual_images.iterdir())
    assert [p.name for p in ecrits] == [f"{meta['id']}.png"]


def _rien_hors_de_images(paths, data_dir) -> None:
    """No file must exist outside `paths.manual_images`."""
    for chemin in data_dir.rglob("*"):
        if chemin.is_file() and chemin.suffix != ".json":
            assert paths.manual_images in chemin.parents, chemin


@pytest.mark.parametrize("identifiant_malveillant", [
    "../../../evil",
    "man-abcd/../../evil",
    "/etc/passwd",
    "C:/temp/evil",
    "evil",
    "man-zzzz",
])
def test_an_identifier_of_invalid_shape_or_path_is_refused(paths, identifiant_malveillant):
    """Direct attacks: the shape validation has to reject everything before any write,
    without depending on what metas.json contains.
    """
    data_dir = paths.data
    with pytest.raises(ManualMetaError):
        save_image(paths, identifiant_malveillant, _png())

    _rien_hors_de_images(paths, data_dir)


def test_an_identifier_present_in_metas_json_but_with_a_path_component_is_refused(paths):
    """The escape the reviewer demonstrated: an id of invalid shape that IS present in
    `metas.json` (e.g. injected by a future import source) must not be enough to get past
    the guard — the shape validation has to precede the file lookup, not depend on it.
    """
    identifiant_malveillant = "../../../evil"
    paths.manual_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(paths.manual_metas, [
        dict(_meta_stub(identifiant_malveillant)),
    ])

    with pytest.raises(ManualMetaError):
        save_image(paths, identifiant_malveillant, _png())

    _rien_hors_de_images(paths, paths.data)
    # The file targeted by the escape (data/evil.png) must not exist.
    assert not (paths.data / "evil.png").exists()


def _meta_stub(meta_id: str) -> dict:
    return {
        "id": meta_id, "country": "PL", "tier": "manual",
        "title": "titre", "description": "description", "category": "autre",
        "source_url": "", "extracted_at": "2026-07-30T00:00:00+00:00",
        "description_origin": "manual", "origin": "manual", "image": None,
    }
