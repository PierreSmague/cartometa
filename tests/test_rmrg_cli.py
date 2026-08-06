from __future__ import annotations

import gzip
import json

import pytest
from pathlib import Path

from cartometa.extract.rmrg_cli import run_extract_rmrg

SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'

PAGE = """
<div class="category-section" id="landscape-section">
  <div class="category-header"><h3 class="category-title">Landscape</h3></div>
  <div class="meta-list">
    <div class="meta-item" id="landscape/water-plots1" data-item-slug="water-plots1">
      <a href="https://maps.app.goo.gl/dkf3fRftJGQCvMet9" class="image-link">
        <div class="base-image"><img src="Bangladesh%20GeoGuessr%20Guide%20-%20RMRG_files/water-plots1_8PNy.webp"></div>
        <div class="svg-overlay-container"><img src="Bangladesh%20GeoGuessr%20Guide%20-%20RMRG_files/water-plots1_8PNy.svg"></div>
      </a>
      <div class="meta-description">Water plots everywhere.</div>
    </div>
    <div class="meta-item" id="landscape/ghost" data-item-slug="ghost">
      <div class="base-image"><img src="Bangladesh%20GeoGuessr%20Guide%20-%20RMRG_files/missing.webp"></div>
      <div class="meta-description">No files on disk for this one.</div>
    </div>
  </div>
</div>
"""


def _write_save(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    assets = input_dir / "Bangladesh GeoGuessr Guide - RMRG_files"
    assets.mkdir(parents=True)
    (assets / "water-plots1_8PNy.webp").write_bytes(b"fake-image")
    (assets / "water-plots1_8PNy.svg").write_bytes(gzip.compress(SVG))
    (input_dir / "Bangladesh GeoGuessr Guide - RMRG.htm").write_text(PAGE, "utf-8")
    # The Plonk It save for the same country must not confuse the lookup.
    (input_dir / "Bangladesh — Plonk It.htm").write_text("<html></html>", "utf-8")
    return input_dir


def test_run_extract_rmrg_writes_the_rmrg_sidecar_file(tmp_path: Path):
    input_dir = _write_save(tmp_path)
    data_dir = tmp_path / "data"

    summary = run_extract_rmrg(input_dir, data_dir, "BD", ["bangladesh"], resolve=False)

    out = data_dir / "metas" / "BD-rmrg.json"
    assert summary["output"] == str(out)
    metas = json.loads(out.read_text("utf-8"))
    assert [m["id"] for m in metas] == ["landscape/ghost", "landscape/water-plots1"]

    plots = metas[1]
    assert plots["origin"] == "rmrg"
    assert plots["tier"] == "regional"
    assert plots["category"] == "landscape"
    assert plots["image"] == "input/Bangladesh GeoGuessr Guide - RMRG_files/water-plots1_8PNy.webp"
    assert plots["overlay"] == "input/Bangladesh GeoGuessr Guide - RMRG_files/water-plots1_8PNy.extracted.svg"
    assert plots["source_url"] == "https://rmrg.me/bangladesh/#landscape/water-plots1"
    # The sidecar really exists and is readable SVG.
    sidecar = input_dir / "Bangladesh GeoGuessr Guide - RMRG_files" / "water-plots1_8PNy.extracted.svg"
    assert sidecar.read_bytes() == SVG


def test_run_extract_rmrg_reports_missing_files_as_anomalies(tmp_path: Path):
    input_dir = _write_save(tmp_path)
    data_dir = tmp_path / "data"

    summary = run_extract_rmrg(input_dir, data_dir, "BD", ["bangladesh"], resolve=False)

    metas = json.loads((data_dir / "metas" / "BD-rmrg.json").read_text("utf-8"))
    ghost = metas[0]
    assert ghost["image"] is None
    assert ghost["overlay"] is None
    assert summary["without_image"] == 1
    assert summary["by_category"] == {"landscape": 2}
    assert any("landscape/ghost" in a for a in summary["anomalies"])


JAVA_PAGE = """
<div class="category-section" id="architecture-section">
  <div class="category-header"><h3 class="category-title">Architecture</h3></div>
  <div class="meta-list">
    <div class="meta-item" id="architecture/joglo-roofs" data-item-slug="joglo-roofs">
      <div class="base-image"><img src="Java%20GeoGuessr%20Guide%20-%20RMRG_files/joglo-roofs_8PNy.webp"></div>
      <div class="meta-description">Joglo roofs are typical of Java.</div>
    </div>
  </div>
</div>
"""


def _write_java_save(input_dir: Path) -> None:
    assets = input_dir / "Java GeoGuessr Guide - RMRG_files"
    assets.mkdir(parents=True)
    (assets / "joglo-roofs_8PNy.webp").write_bytes(b"fake-java-image")
    (input_dir / "Java GeoGuessr Guide - RMRG.htm").write_text(JAVA_PAGE, "utf-8")


def test_several_slugs_merge_into_one_country_file(tmp_path: Path):
    """The Indonesia case: one general guide plus one guide per island, all
    extracted under the same country. Each meta keeps the source_url of its
    own page."""
    input_dir = _write_save(tmp_path)
    _write_java_save(input_dir)
    data_dir = tmp_path / "data"

    summary = run_extract_rmrg(
        input_dir, data_dir, "ID", ["bangladesh", "java"], resolve=False
    )

    metas = json.loads((data_dir / "metas" / "ID-rmrg.json").read_text("utf-8"))
    assert [m["id"] for m in metas] == [
        "architecture/joglo-roofs", "landscape/ghost", "landscape/water-plots1",
    ]
    by_id = {m["id"]: m for m in metas}
    assert by_id["architecture/joglo-roofs"]["source_url"] == (
        "https://rmrg.me/java/#architecture/joglo-roofs"
    )
    assert by_id["landscape/water-plots1"]["source_url"] == (
        "https://rmrg.me/bangladesh/#landscape/water-plots1"
    )
    assert by_id["architecture/joglo-roofs"]["country"] == "ID"
    assert summary["total"] == 3
    assert summary["pages"] == 2


def test_duplicate_ids_across_pages_fail_loudly(tmp_path: Path):
    """Two pages of the same group publishing the same block id would silently
    collapse into one queue entry and one footprint: refusing is the only safe
    answer, with the id and both pages named."""
    input_dir = _write_save(tmp_path)
    java = JAVA_PAGE.replace("architecture/joglo-roofs", "landscape/water-plots1")
    assets = input_dir / "Java GeoGuessr Guide - RMRG_files"
    assets.mkdir(parents=True)
    (assets / "joglo-roofs_8PNy.webp").write_bytes(b"fake")
    (input_dir / "Java GeoGuessr Guide - RMRG.htm").write_text(java, "utf-8")

    with pytest.raises(SystemExit, match="landscape/water-plots1"):
        run_extract_rmrg(
            tmp_path / "input", tmp_path / "data", "ID",
            ["bangladesh", "java"], resolve=False,
        )


def test_run_extract_rmrg_uses_the_shared_maps_cache(tmp_path: Path):
    input_dir = _write_save(tmp_path)
    data_dir = tmp_path / "data"
    cache_path = data_dir / "cache" / "maps_links.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps({"https://maps.app.goo.gl/dkf3fRftJGQCvMet9": [23.5, 90.1]}), "utf-8")

    run_extract_rmrg(input_dir, data_dir, "BD", ["bangladesh"])

    metas = json.loads((data_dir / "metas" / "BD-rmrg.json").read_text("utf-8"))
    assert metas[1]["maps_latlon"] == [23.5, 90.1]
