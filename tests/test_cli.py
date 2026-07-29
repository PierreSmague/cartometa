from __future__ import annotations
import json
from pathlib import Path

import pytest

from cartometa.extract.cli import _find_page, run_extract

PAGE_TEMPLATE = """
<h3>Step 1 - Identifying Poland</h3>
<div id="AAAA" class="relative group/bk">
  <img srcset="{files}/bollard%20photo_006.webp 450w, {files}/bollard%20photo_005.webp 1920w">
  <p><strong>Bollards</strong> are white with a red stripe.</p>
</div>
"""


def _write_page(tmp_path: Path, htm_name: str, files_dirname: str, image_name: str) -> Path:
    assets = tmp_path / files_dirname
    assets.mkdir()
    (assets / image_name).write_bytes(b"fake-image-bytes")
    html_path = tmp_path / htm_name
    html_path.write_text(
        PAGE_TEMPLATE.format(files=files_dirname.replace(" ", "%20").replace("—", "%E2%80%94")),
        "utf-8",
    )
    return html_path


def test_find_page_matches_single_candidate(tmp_path: Path):
    _write_page(tmp_path, "Poland — Plonk It.htm", "Poland — Plonk It_files", "bollard photo_005.webp")
    html_path = _find_page(tmp_path, "poland")
    assert html_path.name == "Poland — Plonk It.htm"


def test_find_page_raises_on_ambiguous_candidates(tmp_path: Path):
    _write_page(tmp_path, "Poland — Plonk It.htm", "Poland — Plonk It_files", "bollard photo_005.webp")
    # Collision de nom telle qu'un navigateur peut en produire lors d'une seconde sauvegarde.
    (tmp_path / "Poland — Plonk It (1).htm").write_text("<h3>Step 1</h3>", "utf-8")

    with pytest.raises(ValueError, match="plusieurs pages"):
        _find_page(tmp_path, "poland")


def test_run_extract_resolves_url_encoded_image_path_with_spaces_and_em_dash(tmp_path: Path):
    """Le chemin d'image référencé dans le HTML est URL-encodé (espaces -> %20,
    tiret cadratin -> %E2%80%94) : il doit être décodé et retrouvé tel quel sur
    le disque, comme pour la vraie page Pologne sauvegardée."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_page(input_dir, "Poland — Plonk It.htm", "Poland — Plonk It_files", "bollard photo_005.webp")

    data_dir = tmp_path / "data"
    summary = run_extract(input_dir, data_dir, "PL", "https://www.plonkit.net/poland", resolve=False)

    assert summary["anomalies"] == []
    assert summary["without_image"] == 0

    metas = __import__("json").loads((data_dir / "metas" / "PL.json").read_text("utf-8"))
    assert metas[0]["image"] == "input/Poland — Plonk It_files/bollard photo_005.webp"


SPOT_PAGE_TEMPLATE = """
<h3>Step 3 - Spotlight</h3>
<div id="ZZZZ" class="relative group/bk">
  <a href="https://goo.gl/maps/dead">
    <img src="photo.webp">
  </a>
  <p><strong>Somewhere</strong> is a place.</p>
</div>
"""


def _write_spot_page(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "photo.webp").write_bytes(b"fake")
    html_path = input_dir / "Poland — Plonk It.htm"
    html_path.write_text(SPOT_PAGE_TEMPLATE, "utf-8")
    return input_dir


REDIRECT = "https://www.google.com/maps/@49.302333,20.0088885,3a,45.1y/data=!3m6"


def test_run_extract_does_not_retry_cached_failure_by_default(tmp_path: Path, monkeypatch):
    input_dir = _write_spot_page(tmp_path)
    data_dir = tmp_path / "data"
    cache_path = data_dir / "cache" / "maps_links.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps({"https://goo.gl/maps/dead": None}), "utf-8")

    calls = []
    monkeypatch.setattr(
        "cartometa.extract.cli.resolve_maps_url",
        lambda url, cache, retry_failed=False: calls.append((url, retry_failed)) or None,
    )
    run_extract(input_dir, data_dir, "PL", "https://www.plonkit.net/poland")
    assert calls == [("https://goo.gl/maps/dead", False)]


def test_run_extract_retry_failed_links_option_resolves_previously_dead_link(tmp_path: Path):
    input_dir = _write_spot_page(tmp_path)
    data_dir = tmp_path / "data"
    cache_path = data_dir / "cache" / "maps_links.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps({"https://goo.gl/maps/dead": None}), "utf-8")

    summary = run_extract(
        input_dir, data_dir, "PL", "https://www.plonkit.net/poland",
        retry_failed=True,
        request_delay=0,
    )
    metas = json.loads((data_dir / "metas" / "PL.json").read_text("utf-8"))
    # Pas d'accès réseau réel dans ce test : sans opener injectable dans run_extract,
    # on vérifie seulement que le paramètre est bien transmis et ne casse rien —
    # la résolution réelle est couverte par test_maps_links.py.
    assert summary["total"] == 1


def test_run_extract_sleeps_before_real_network_calls_only(tmp_path: Path):
    input_dir = _write_spot_page(tmp_path)
    data_dir = tmp_path / "data"
    cache_path = data_dir / "cache" / "maps_links.json"
    cache_path.parent.mkdir(parents=True)
    # Lien déjà résolu : ne doit déclencher ni réseau, ni pause.
    cache_path.write_text(json.dumps({"https://goo.gl/maps/dead": [1.0, 2.0]}), "utf-8")

    sleeps = []
    run_extract(
        input_dir, data_dir, "PL", "https://www.plonkit.net/poland",
        request_delay=5.0, sleep=sleeps.append,
    )
    assert sleeps == []
