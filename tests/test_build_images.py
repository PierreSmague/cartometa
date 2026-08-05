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


def test_both_sizes_are_produced(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1920, 950)

    noms = render_image_pair(source, tmp_path / "out", "a")

    assert set(noms) == {"thumb", "full"}
    for nom in noms.values():
        assert (tmp_path / "out" / nom).exists()


def test_the_thumbnail_and_the_full_size_respect_their_widths(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1920, 950)

    noms = render_image_pair(source, tmp_path / "out", "a")

    with Image.open(tmp_path / "out" / noms["thumb"]) as vignette:
        assert vignette.width == THUMB_WIDTH
    with Image.open(tmp_path / "out" / noms["full"]) as pleine:
        assert pleine.width == FULL_WIDTH


def test_an_image_smaller_than_the_target_is_never_upscaled(tmp_path):
    source = _image(tmp_path / "src" / "petite.png", 400, 200)

    noms = render_image_pair(source, tmp_path / "out", "petite")

    with Image.open(tmp_path / "out" / noms["full"]) as pleine:
        assert pleine.width == 400


def test_the_output_is_webp(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1000, 500)

    noms = render_image_pair(source, tmp_path / "out", "a")

    assert noms["full"].endswith(".webp")
    with Image.open(tmp_path / "out" / noms["full"]) as pleine:
        assert pleine.format == "WEBP"


def test_the_names_carry_a_fingerprint_and_differ(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1000, 500)

    noms = render_image_pair(source, tmp_path / "out", "a")

    assert noms["thumb"] != noms["full"]
    assert noms["thumb"].startswith("a.t.")
    assert noms["full"].startswith("a.f.")


def test_a_missing_source_raises_an_explicit_error(tmp_path):
    with pytest.raises(MissingImageError, match="not found"):
        render_image_pair(tmp_path / "absente.png", tmp_path / "out", "x")
