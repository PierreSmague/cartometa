import pytest
from PIL import Image

from cartometa.build.images import (
    FULL_WIDTH,
    THUMB_WIDTH,
    MissingImageError,
    render_image_pair,
)


def _image(chemin, largeur, hauteur):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (largeur, hauteur), (120, 90, 60)).save(chemin)
    return chemin


def test_les_deux_tailles_sont_produites(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1920, 950)

    noms = render_image_pair(source, tmp_path / "out", "a")

    assert set(noms) == {"thumb", "full"}
    for nom in noms.values():
        assert (tmp_path / "out" / nom).exists()


def test_la_vignette_et_la_pleine_respectent_leur_largeur(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1920, 950)

    noms = render_image_pair(source, tmp_path / "out", "a")

    with Image.open(tmp_path / "out" / noms["thumb"]) as vignette:
        assert vignette.width == THUMB_WIDTH
    with Image.open(tmp_path / "out" / noms["full"]) as pleine:
        assert pleine.width == FULL_WIDTH


def test_une_image_plus_petite_que_la_cible_n_est_jamais_agrandie(tmp_path):
    source = _image(tmp_path / "src" / "petite.png", 400, 200)

    noms = render_image_pair(source, tmp_path / "out", "petite")

    with Image.open(tmp_path / "out" / noms["full"]) as pleine:
        assert pleine.width == 400


def test_la_sortie_est_du_webp(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1000, 500)

    noms = render_image_pair(source, tmp_path / "out", "a")

    assert noms["full"].endswith(".webp")
    with Image.open(tmp_path / "out" / noms["full"]) as pleine:
        assert pleine.format == "WEBP"


def test_les_noms_portent_une_empreinte_et_se_distinguent(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1000, 500)

    noms = render_image_pair(source, tmp_path / "out", "a")

    assert noms["thumb"] != noms["full"]
    assert noms["thumb"].startswith("a.t.")
    assert noms["full"].startswith("a.f.")


def test_une_source_absente_leve_une_erreur_explicite(tmp_path):
    with pytest.raises(MissingImageError, match="introuvable"):
        render_image_pair(tmp_path / "absente.png", tmp_path / "out", "x")
