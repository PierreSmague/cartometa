import json
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
