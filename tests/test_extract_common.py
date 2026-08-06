from __future__ import annotations
import json
from pathlib import Path

import pytest

from cartometa.extract.common import find_page, project_relative_path, resolve_meta_links
from cartometa.models import MetaRecord


def _meta(maps_url=None):
    return MetaRecord(
        id="x", country="PL", tier="regional", title="t", description="d",
        category="autre", source_url="https://example.test#x",
        extracted_at="2026-08-06T00:00:00+00:00", maps_url=maps_url,
    )


def test_find_page_matches_single_candidate(tmp_path: Path):
    (tmp_path / "Poland — Plonk It.htm").write_text("<html></html>", "utf-8")
    assert find_page(tmp_path, "poland").name == "Poland — Plonk It.htm"


def test_find_page_raises_on_ambiguous_candidates(tmp_path: Path):
    (tmp_path / "Poland — Plonk It.htm").write_text("<html></html>", "utf-8")
    # A name collision of the kind a browser can produce on a second save.
    (tmp_path / "Poland — Plonk It (1).htm").write_text("<html></html>", "utf-8")
    with pytest.raises(ValueError, match="several saved pages"):
        find_page(tmp_path, "poland")


def test_page_found_despite_the_slug_dashes(tmp_path: Path):
    """The URL slug is written "south-africa", the browser saves "South Africa"."""
    (tmp_path / "South Africa — Plonk It.htm").write_text("<html></html>", "utf-8")
    assert find_page(tmp_path, "south-africa").name == "South Africa — Plonk It.htm"


def test_a_missing_page_lists_the_available_pages(tmp_path: Path):
    (tmp_path / "Poland — Plonk It.htm").write_text("<html></html>", "utf-8")
    with pytest.raises(FileNotFoundError, match="Poland"):
        find_page(tmp_path, "south-africa")


def test_find_page_ignores_rmrg_saves_by_default(tmp_path: Path):
    """Both sources saved for the same country: the Plonk It side must not become
    ambiguous because "Bangladesh GeoGuessr Guide - RMRG" also contains the slug."""
    (tmp_path / "Bangladesh — Plonk It.htm").write_text("<html></html>", "utf-8")
    (tmp_path / "Bangladesh GeoGuessr Guide - RMRG.htm").write_text("<html></html>", "utf-8")
    assert find_page(tmp_path, "bangladesh").name == "Bangladesh — Plonk It.htm"


def test_find_page_rmrg_selects_the_rmrg_save(tmp_path: Path):
    (tmp_path / "Bangladesh — Plonk It.htm").write_text("<html></html>", "utf-8")
    (tmp_path / "Bangladesh GeoGuessr Guide - RMRG.htm").write_text("<html></html>", "utf-8")
    page = find_page(tmp_path, "bangladesh", rmrg=True)
    assert page.name == "Bangladesh GeoGuessr Guide - RMRG.htm"


def test_find_page_treats_ampersand_as_a_separator(tmp_path: Path):
    """The rmrg.me slug is "sulawesi-maluku" but the browser saves
    "Sulawesi & Maluku GeoGuessr Guide - RMRG.htm": without normalising the
    ampersand away, the multi-page Indonesia group is unfindable."""
    (tmp_path / "Sulawesi & Maluku GeoGuessr Guide - RMRG.htm").write_text("<html></html>", "utf-8")
    page = find_page(tmp_path, "sulawesi-maluku", rmrg=True)
    assert page.name == "Sulawesi & Maluku GeoGuessr Guide - RMRG.htm"


def test_find_page_rmrg_missing_even_if_plonkit_exists(tmp_path: Path):
    (tmp_path / "Bangladesh — Plonk It.htm").write_text("<html></html>", "utf-8")
    with pytest.raises(FileNotFoundError):
        find_page(tmp_path, "bangladesh", rmrg=True)


def test_project_relative_path_decodes_and_normalises(tmp_path: Path):
    input_dir = tmp_path / "input"
    assets = input_dir / "Poland — Plonk It_files"
    assets.mkdir(parents=True)
    (assets / "photo.webp").write_bytes(b"fake")
    html_path = input_dir / "Poland — Plonk It.htm"
    html_path.write_text("<html></html>", "utf-8")
    assert (
        project_relative_path(html_path, input_dir, "Poland — Plonk It_files/photo.webp")
        == "input/Poland — Plonk It_files/photo.webp"
    )


def test_project_relative_path_returns_none_when_missing(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    html_path = input_dir / "Poland — Plonk It.htm"
    html_path.write_text("<html></html>", "utf-8")
    assert project_relative_path(html_path, input_dir, "nope/photo.webp") is None


def test_resolve_meta_links_skips_network_when_resolve_is_false(tmp_path: Path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "cartometa.extract.common.resolve_maps_url",
        lambda url, cache, retry_failed=False: calls.append(url) or None,
    )
    meta = _meta(maps_url="https://goo.gl/maps/dead")
    resolve_meta_links([meta], tmp_path / "cache.json", resolve=False,
                       retry_failed=False, request_delay=0.0, sleep=lambda s: None)
    assert calls == []
    assert meta.maps_latlon is None


def test_resolve_meta_links_sleeps_only_before_real_network_calls(tmp_path: Path, monkeypatch):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"https://goo.gl/maps/dead": [1.0, 2.0]}), "utf-8")
    sleeps = []
    meta = _meta(maps_url="https://goo.gl/maps/dead")
    resolve_meta_links([meta], cache_path, resolve=True,
                       retry_failed=False, request_delay=5.0, sleep=sleeps.append)
    assert sleeps == []
    assert meta.maps_latlon == (1.0, 2.0)
