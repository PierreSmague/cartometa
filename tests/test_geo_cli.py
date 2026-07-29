from __future__ import annotations
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import box

from cartometa.config import load_config
from cartometa.geo import cli as geo_cli
from cartometa.geo.calibrate import fit_calibration, save_calibration

CREAM = (255, 253, 235, 255)
RED = (193, 40, 58, 255)
COUNTRY = box(14.0, 49.0, 24.0, 55.0)


def _rect_mask(shape=(400, 400), x0=100, x1=300, y0=50, y1=250):
    mask = np.zeros(shape, dtype=bool)
    mask[y0:y1, x0:x1] = True
    return mask


def _make_regional_image(*, touching_country_bbox: bool) -> Image.Image:
    """Image composite synthétique (200x160) avec un encart crème rectangulaire
    et une zone rouge positionnée près du bord de la silhouette du pays, ou
    bien confortablement à l'intérieur.

    Le rectangle crème (l'encart, loin de tout bord réel de l'image) reste
    identique dans les deux cas : seule la position du rouge change. Cela
    isole précisément ce que `touches_border` est censé mesurer — le contact
    avec la bbox de la silhouette du pays — de toute question de cadrage
    physique de l'image (hors sujet depuis la correction : voir cli.py).
    """
    width, height = 200, 160
    img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    rect = (20, 20, 180, 140)
    # Même taille de zone rouge (20x20) dans les deux cas : seule la position
    # change, pour isoler l'effet de `touches_border` de tout autre facteur
    # (ex. fraction de surface du pays) qui influerait aussi sur le score.
    if touching_country_bbox:
        # Rouge collé au coin de la silhouette du pays (bord de inset.bbox).
        red_box = (20, 20, 40, 40)
    else:
        # Rouge bien à l'intérieur, ne touche aucun bord de la silhouette.
        red_box = (90, 70, 110, 90)

    draw.rectangle(rect, fill=CREAM)
    draw.rectangle(red_box, fill=RED)
    return img


def _write_meta_image(tmp_path: Path, name: str, image: Image.Image) -> str:
    rel = Path("input") / f"{name}.png"
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    image.save(tmp_path / rel)
    return str(rel).replace("\\", "/")


def _setup(tmp_path: Path, metas: list[dict]) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "metas").mkdir(parents=True)
    (data_dir / "metas" / "PL.json").write_text(json.dumps(metas), "utf-8")

    calib = fit_calibration(_rect_mask(), COUNTRY, load_config())
    save_calibration(data_dir / "calib" / "PL.json", calib)
    return data_dir


def _base_meta(**overrides) -> dict:
    meta = {
        "id": "XXXX", "country": "PL", "tier": "spot", "title": "t", "description": "d",
        "description_origin": "imported", "category": "autre", "image": None,
        "maps_url": None, "maps_latlon": None, "source_url": "https://example/#XXXX",
        "extracted_at": "2026-01-01T00:00:00+00:00",
    }
    meta.update(overrides)
    return meta


def test_spot_with_unresolved_maps_url_gets_specific_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(geo_cli, "country_geometry", lambda *a, **k: COUNTRY)
    metas = [_base_meta(id="SPOT_URL", tier="spot", maps_url="https://goo.gl/maps/dead", maps_latlon=None)]
    data_dir = _setup(tmp_path, metas)

    geo_cli.build_country("PL", data_dir, load_config())
    geo = json.loads((data_dir / "geo" / "PL.geojson").read_text("utf-8"))
    props = geo["features"][0]["properties"]
    assert "lien Maps présent mais non résolu" in props["warnings"]
    assert "méta ponctuelle sans lien Maps, position inconnue" not in props["warnings"]


def test_spot_without_any_maps_url_gets_generic_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(geo_cli, "country_geometry", lambda *a, **k: COUNTRY)
    metas = [_base_meta(id="SPOT_NONE", tier="spot", maps_url=None, maps_latlon=None)]
    data_dir = _setup(tmp_path, metas)

    geo_cli.build_country("PL", data_dir, load_config())
    geo = json.loads((data_dir / "geo" / "PL.geojson").read_text("utf-8"))
    props = geo["features"][0]["properties"]
    assert "méta ponctuelle sans lien Maps, position inconnue" in props["warnings"]
    assert "lien Maps présent mais non résolu" not in props["warnings"]


def test_regional_zone_touching_country_bbox_is_reported_without_truncation_or_penalty(tmp_path, monkeypatch):
    """Correction (relecture finale) : toucher la bbox de la silhouette du
    pays reste rapporté (c'est l'information réellement mesurée), mais ne
    doit plus prétendre à une troncature de l'image ni faire baisser le
    score de confiance — sans quoi une méta régionale par ailleurs correcte
    remonte à tort en tête de la file de revue."""
    monkeypatch.setattr(geo_cli, "country_geometry", lambda *a, **k: COUNTRY)
    touching_image = _make_regional_image(touching_country_bbox=True)
    inside_image = _make_regional_image(touching_country_bbox=False)
    rel_touching = _write_meta_image(tmp_path, "reg_a", touching_image)
    rel_inside = _write_meta_image(tmp_path, "reg_b", inside_image)
    metas = [
        _base_meta(id="REG_TOUCHING", tier="regional", image=rel_touching),
        _base_meta(id="REG_INSIDE", tier="regional", image=rel_inside),
    ]
    data_dir = _setup(tmp_path, metas)

    import os
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        geo_cli.build_country("PL", data_dir, load_config())
    finally:
        os.chdir(old_cwd)
    geo = json.loads((data_dir / "geo" / "PL.geojson").read_text("utf-8"))
    by_id = {f["properties"]["id"]: f["properties"] for f in geo["features"]}

    touching_props, inside_props = by_id["REG_TOUCHING"], by_id["REG_INSIDE"]
    assert any("silhouette du pays" in w for w in touching_props["warnings"])
    # L'ancienne formulation affirmait une troncature possible ; la nouvelle la
    # nie explicitement — on vérifie qu'aucune ne l'affirme plus.
    assert not any("possiblement tronquée" in w for w in touching_props["warnings"])
    assert not any("silhouette du pays" in w for w in inside_props["warnings"])
    # L'absence de malus pour ce signal précis est vérifiée unitairement, sans
    # confusion possible avec d'autres avertissements géométriques, dans
    # test_confidence.py::test_border_touching_zone_is_reported_without_truncation_claim_or_penalty.


def test_build_country_writes_atomically_no_leftover_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(geo_cli, "country_geometry", lambda *a, **k: COUNTRY)
    metas = [_base_meta(id="CTRY1", tier="country")]
    data_dir = _setup(tmp_path, metas)

    geo_cli.build_country("PL", data_dir, load_config())
    out_path = data_dir / "geo" / "PL.geojson"
    assert out_path.exists()
    assert not out_path.with_suffix(out_path.suffix + ".tmp").exists()
    # Le contenu doit être un JSON valide et complet.
    data = json.loads(out_path.read_text("utf-8"))
    assert data["type"] == "FeatureCollection"


def test_build_country_preserves_existing_geojson_on_write_failure(tmp_path, monkeypatch):
    """La méthode d'écriture doit passer par cartometa.atomic_write : si le
    remplacement final échoue, le fichier précédent (travail de revue humain)
    doit rester intact plutôt que d'être tronqué."""
    monkeypatch.setattr(geo_cli, "country_geometry", lambda *a, **k: COUNTRY)
    metas = [_base_meta(id="CTRY1", tier="country")]
    data_dir = _setup(tmp_path, metas)

    geo_cli.build_country("PL", data_dir, load_config())
    out_path = data_dir / "geo" / "PL.geojson"
    previous_content = out_path.read_text("utf-8")

    monkeypatch.setattr("cartometa.atomic_write.os.replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disque plein")))
    try:
        geo_cli.build_country("PL", data_dir, load_config())
    except OSError:
        pass

    assert out_path.read_text("utf-8") == previous_content
