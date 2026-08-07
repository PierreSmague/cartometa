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


# A solid red square: composited, it turns any pixel it covers red, and its
# 1:1 ratio makes the expected geometry easy to compute by hand.
_SVG_CARRE_ROUGE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
    'viewBox="0 0 100 100"><rect width="100" height="100" fill="#e00000"/></svg>'
)


def _svg(chemin, contenu=_SVG_CARRE_ROUGE):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, "utf-8")
    return chemin


def test_the_overlay_is_composited_bottom_right_within_a_ninth(tmp_path):
    """The trace occupies the bottom-right 1/3 x 1/3 box, and nothing more.

    Source 1500x900 -> full resized to 1400x840, box 466x280; the square SVG
    contain-fits to 280x280 anchored at the corner.
    """
    source = _image(tmp_path / "src" / "a.png", 1500, 900)
    overlay = _svg(tmp_path / "src" / "trace.svg")

    noms = render_image_pair(source, tmp_path / "out", "a", overlay=overlay)

    with Image.open(tmp_path / "out" / noms["full"]) as pleine:
        pleine = pleine.convert("RGB")
        assert pleine.getpixel((1399, 839))[0] > 180      # corner: red
        assert pleine.getpixel((1399 - 285, 839)) == pytest.approx(
            (120, 90, 60), abs=12
        )                                                  # left of the box: base
        assert pleine.getpixel((1399, 839 - 285)) == pytest.approx(
            (120, 90, 60), abs=12
        )                                                  # above the box: base
        assert pleine.getpixel((0, 0)) == pytest.approx((120, 90, 60), abs=12)


def test_the_thumbnail_carries_the_overlay_too(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1500, 900)
    overlay = _svg(tmp_path / "src" / "trace.svg")

    noms = render_image_pair(source, tmp_path / "out", "a", overlay=overlay)

    with Image.open(tmp_path / "out" / noms["thumb"]) as vignette:
        vignette = vignette.convert("RGB")
        assert vignette.getpixel((vignette.width - 1, vignette.height - 1))[0] > 180


def test_the_overlay_transparency_lets_the_photo_show_through(tmp_path):
    """The RMRG mini-maps are transparent outside the country outline: the
    photo has to stay visible there, not be blanked by a white rectangle."""
    source = _image(tmp_path / "src" / "a.png", 1500, 900)
    # Opaque red only in the bottom half; the top half of the box stays photo.
    overlay = _svg(
        tmp_path / "src" / "trace.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
        'viewBox="0 0 100 100"><rect y="50" width="100" height="50" '
        'fill="#e00000"/></svg>',
    )

    noms = render_image_pair(source, tmp_path / "out", "a", overlay=overlay)

    with Image.open(tmp_path / "out" / noms["full"]) as pleine:
        pleine = pleine.convert("RGB")
        assert pleine.getpixel((1399, 839))[0] > 180               # opaque half
        assert pleine.getpixel((1399, 839 - 200)) == pytest.approx(
            (120, 90, 60), abs=12
        )                                                          # transparent half


def test_with_and_without_overlay_do_not_share_a_cache_entry(tmp_path):
    """Same photo, with then without trace: two distinct cache keys.

    Otherwise the second build would serve whichever variant was encoded
    first — a silently wrong image on half the metas."""
    from cartometa.build.image_cache import ImageCache

    source = _image(tmp_path / "src" / "a.png", 1500, 900)
    overlay = _svg(tmp_path / "src" / "trace.svg")
    cache = ImageCache(tmp_path / "cache")

    avec = render_image_pair(source, tmp_path / "o1", "a", cache, overlay=overlay)
    sans = render_image_pair(source, tmp_path / "o2", "a", cache)

    assert avec["full"] != sans["full"]
    with Image.open(tmp_path / "o2" / sans["full"]) as pleine:
        pleine = pleine.convert("RGB")
        assert pleine.getpixel((1399, 839)) == pytest.approx((120, 90, 60), abs=12)


def test_a_missing_overlay_raises_an_explicit_error(tmp_path):
    """input/ is not versioned: a fresh clone can hold the metas JSON but not
    the saved pages. Same failure mode as the photo, same explicit error."""
    source = _image(tmp_path / "src" / "a.png", 1500, 900)

    with pytest.raises(MissingImageError, match="not found"):
        render_image_pair(
            source, tmp_path / "out", "a", overlay=tmp_path / "absent.svg"
        )
