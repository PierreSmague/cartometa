"""Cache d'encodage des images.

Le build fait table rase de `dist/` à chaque appel et réencode tout. À 1922
emprises, une publication qui n'ajoute que quelques métas repayait ~10 min
de travail identique au build précédent. Ces tests fixent le contrat du
cache qui l'évite.
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
    """Fait échouer tout encodage : ce qui passe vient forcément du cache."""

    def interdit(*args, **kwargs):
        raise AssertionError("image réencodée alors que le cache la contenait")

    monkeypatch.setattr(images, "_encode", interdit)


def test_une_entree_corrompue_est_ignoree_et_reencodee(tmp_path):
    """Le pire défaut possible ici : servir une image tronquée sans le dire.

    Une entrée abîmée doit coûter un réencodage, jamais produire un `dist/`
    dont la vérification d'intégrité ne verrait rien — le fichier existe, il
    est simplement illisible.
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


def test_une_seconde_construction_ne_reencode_pas(tmp_path, monkeypatch):
    source = _image(tmp_path / "src" / "a.png", 1000, 500)
    cache = ImageCache(tmp_path / "cache")

    premiers = render_image_pair(source, tmp_path / "out1", "a", cache)
    _interdire_encodage(monkeypatch)
    seconds = render_image_pair(source, tmp_path / "out2", "a", cache)

    assert seconds == premiers
    for variante in ("thumb", "full"):
        attendu = (tmp_path / "out1" / premiers[variante]).read_bytes()
        assert (tmp_path / "out2" / seconds[variante]).read_bytes() == attendu


def test_le_cache_suit_le_contenu_et_non_le_chemin(tmp_path, monkeypatch):
    """Deux copies d'une même capture ne doivent être encodées qu'une fois."""
    source = _image(tmp_path / "src" / "a.png", 1000, 500)
    cache = ImageCache(tmp_path / "cache")
    premiers = render_image_pair(source, tmp_path / "out1", "a", cache)

    ailleurs = tmp_path / "autre" / "b.png"
    ailleurs.parent.mkdir(parents=True)
    ailleurs.write_bytes(source.read_bytes())
    _interdire_encodage(monkeypatch)

    seconds = render_image_pair(ailleurs, tmp_path / "out2", "b", cache)

    assert seconds["thumb"].startswith("b.t."), "le nom publié suit bien la méta"
    attendu = (tmp_path / "out1" / premiers["thumb"]).read_bytes()
    assert (tmp_path / "out2" / seconds["thumb"]).read_bytes() == attendu


def test_un_changement_de_reglages_invalide_le_cache(tmp_path, monkeypatch):
    """Sinon le site servirait des images encodées selon des réglages morts."""
    source = _image(tmp_path / "src" / "a.png", 1000, 500)
    cache = ImageCache(tmp_path / "cache")
    render_image_pair(source, tmp_path / "out1", "a", cache)

    monkeypatch.setattr(images, "SIGNATURE", "v2-autres-reglages")
    _interdire_encodage(monkeypatch)

    with pytest.raises(AssertionError, match="réencodée"):
        render_image_pair(source, tmp_path / "out2", "a", cache)


def test_sans_cache_le_comportement_est_inchange(tmp_path):
    """Le cache est facultatif : `render_image_pair` reste utilisable seul."""
    source = _image(tmp_path / "src" / "a.png", 1000, 500)

    avec = render_image_pair(source, tmp_path / "out1", "a", ImageCache(tmp_path / "c"))
    sans = render_image_pair(source, tmp_path / "out2", "a")

    assert sans == avec
