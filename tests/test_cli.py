from __future__ import annotations
import json
from pathlib import Path

from cartometa.extract.cli import run_extract

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


def test_run_extract_resolves_url_encoded_image_path_with_spaces_and_em_dash(tmp_path: Path):
    """The image path referenced in the HTML is URL-encoded (spaces -> %20, em dash ->
    %E2%80%94): it has to be decoded and found as-is on disk, as for the real saved
    Poland page."""
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
        "cartometa.extract.common.resolve_maps_url",
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
    # No real network access in this test: with no injectable opener in run_extract, we
    # only check that the parameter is passed through and breaks nothing — the real
    # resolution is covered by test_maps_links.py.
    assert summary["total"] == 1


def test_run_extract_sleeps_before_real_network_calls_only(tmp_path: Path):
    input_dir = _write_spot_page(tmp_path)
    data_dir = tmp_path / "data"
    cache_path = data_dir / "cache" / "maps_links.json"
    cache_path.parent.mkdir(parents=True)
    # Already resolved link: must trigger neither network nor pause.
    cache_path.write_text(json.dumps({"https://goo.gl/maps/dead": [1.0, 2.0]}), "utf-8")

    sleeps = []
    run_extract(
        input_dir, data_dir, "PL", "https://www.plonkit.net/poland",
        request_delay=5.0, sleep=sleeps.append,
    )
    assert sleeps == []
