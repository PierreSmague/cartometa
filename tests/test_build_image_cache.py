"""Image encoding cache.

The build wipes `dist/` on every call and re-encodes everything. At 1922 footprints, a
publication that only adds a few metas paid ~10 min of work identical to the previous
build all over again. These tests fix the contract of the cache that avoids it.
"""

import pytest
from PIL import Image

import cartometa.build.images as images

from cartometa.build.image_cache import ImageCache
from cartometa.build.images import render_image_pair


def _image(chemin, largeur, hauteur, couleur=(120, 90, 60)):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (largeur, hauteur), couleur).save(chemin)
    return chemin


def _interdire_encodage(monkeypatch):
    """Makes any encoding fail: whatever passes necessarily comes from the cache."""

    def interdit(*args, **kwargs):
        raise AssertionError("image re-encoded although the cache held it")

    monkeypatch.setattr(images, "_encode", interdit)


def test_a_corrupted_entry_is_ignored_and_re_encoded(tmp_path):
    """The worst possible defect here: serving a truncated image without saying so.

    A damaged entry must cost a re-encode, never produce a `dist/` whose integrity
    check would see nothing — the file exists, it is simply unreadable.
    """
    source = _image(tmp_path / "src" / "a.png", 1000, 500)
    cache = ImageCache(tmp_path / "cache")
    premiers = render_image_pair(source, tmp_path / "out1", "a", cache)

    entree = next(p for p in (tmp_path / "cache").rglob("*") if p.is_file())
    entree.write_bytes(b"octets tronques")

    seconds = render_image_pair(source, tmp_path / "out2", "a", cache)

    assert seconds == premiers
    for variante in ("thumb", "full"):
        attendu = (tmp_path / "out1" / premiers[variante]).read_bytes()
        assert (tmp_path / "out2" / seconds[variante]).read_bytes() == attendu


def test_a_second_build_does_not_re_encode(tmp_path, monkeypatch):
    source = _image(tmp_path / "src" / "a.png", 1000, 500)
    cache = ImageCache(tmp_path / "cache")

    premiers = render_image_pair(source, tmp_path / "out1", "a", cache)
    _interdire_encodage(monkeypatch)
    seconds = render_image_pair(source, tmp_path / "out2", "a", cache)

    assert seconds == premiers
    for variante in ("thumb", "full"):
        attendu = (tmp_path / "out1" / premiers[variante]).read_bytes()
        assert (tmp_path / "out2" / seconds[variante]).read_bytes() == attendu


def test_the_cache_follows_the_content_not_the_path(tmp_path, monkeypatch):
    """Two copies of the same screenshot must only be encoded once."""
    source = _image(tmp_path / "src" / "a.png", 1000, 500)
    cache = ImageCache(tmp_path / "cache")
    premiers = render_image_pair(source, tmp_path / "out1", "a", cache)

    ailleurs = tmp_path / "autre" / "b.png"
    ailleurs.parent.mkdir(parents=True)
    ailleurs.write_bytes(source.read_bytes())
    _interdire_encodage(monkeypatch)

    seconds = render_image_pair(ailleurs, tmp_path / "out2", "b", cache)

    assert seconds["thumb"].startswith("b.t."), "the published name does follow the meta"
    attendu = (tmp_path / "out1" / premiers["thumb"]).read_bytes()
    assert (tmp_path / "out2" / seconds["thumb"]).read_bytes() == attendu


def test_a_settings_change_invalidates_the_cache(tmp_path, monkeypatch):
    """Otherwise the site would serve images encoded according to dead settings."""
    source = _image(tmp_path / "src" / "a.png", 1000, 500)
    cache = ImageCache(tmp_path / "cache")
    render_image_pair(source, tmp_path / "out1", "a", cache)

    monkeypatch.setattr(images, "SIGNATURE", "v2-autres-reglages")
    _interdire_encodage(monkeypatch)

    with pytest.raises(AssertionError, match="re-encoded"):
        render_image_pair(source, tmp_path / "out2", "a", cache)


def test_without_a_cache_the_behaviour_is_unchanged(tmp_path):
    """The cache is optional: `render_image_pair` stays usable on its own."""
    source = _image(tmp_path / "src" / "a.png", 1000, 500)

    avec = render_image_pair(source, tmp_path / "out1", "a", ImageCache(tmp_path / "c"))
    sans = render_image_pair(source, tmp_path / "out2", "a")

    assert sans == avec
