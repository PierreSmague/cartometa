# cartometa-extract-rmrg Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Importer les métas des guides RMRG (`rmrg.me`) dans le pipeline Cartometa via une nouvelle commande `cartometa-extract-rmrg`, avec affichage de la mini-carte SVG RMRG dans la revue.

**Architecture:** Un parser dédié (`cartometa/extract/rmrg.py`) et une CLI dédiée (`cartometa/extract/rmrg_cli.py`) qui écrivent `data/metas/<CC>-rmrg.json`, à côté du fichier Plonk It. Les briques communes aux deux extracteurs (recherche de page, résolution des liens Maps, chemins relatifs projet) sont factorisées dans `cartometa/extract/common.py`. Le stockage ne change qu'en un point : `load_metas` lit trois fichiers au lieu de deux.

**Tech Stack:** Python 3.14, selectolax, pytest. Gestion via `uv` (mémoire projet : les exécutables vivent dans `.venv\Scripts\` si `uv` est bloqué par Smart App Control).

**Spec:** `docs/superpowers/specs/2026-08-06-extract-rmrg-design.md`

## Global Constraints

- Sortie extracteur : `data/metas/<CC>-rmrg.json`, même format JSON que Plonk It (liste de `MetaRecord.to_dict()`, indent=2, ensure_ascii=False, triée par id).
- Nouvelles constantes : `ORIGIN_RMRG = "rmrg"` dans `cartometa/models.py` ; champ `MetaRecord.overlay: str | None = None`.
- Tier constant `TIER_REGIONAL` pour toutes les métas RMRG ; catégorie depuis la section h3 (`agriculture` → `vegetation`, cinq autres 1:1, inconnu → `autre` + anomalie).
- La sauvegarde navigateur sous `input/` n'est JAMAIS modifiée : les SVG gzippés sont décompressés vers des sidecars `*.extracted.svg`.
- Comportement Plonk It strictement inchangé (mêmes fichiers de sortie, même cache `data/cache/maps_links.json` partagé).
- Le champ `overlay` est exposé dans la queue de revue mais PAS publié par `build_dataset`.
- Commandes de test : `uv run pytest tests/... -v` (depuis la racine du projet).
- ATTENTION (mémoire projet) : si un serveur de revue tourne, `data/geo/` bouge en continu — ne jamais faire de stash/checkout/reset avec ces fichiers modifiés. Ce plan ne touche pas `data/geo/`, aucun commit ne doit inclure `data/`.

---

### Task 1: Module commun `cartometa/extract/common.py`

Factoriser les briques partagées par les deux CLI : recherche de page (avec discrimination RMRG/Plonk It), garde réseau, chemin relatif projet, boucle de résolution des liens Maps. Adapter `cli.py` et les tests existants.

**Files:**
- Create: `cartometa/extract/common.py`
- Create: `tests/test_extract_common.py`
- Modify: `cartometa/extract/cli.py` (retirer `_find_page` et `_would_hit_network`, utiliser common)
- Modify: `tests/test_cli.py` (imports et cible du monkeypatch)

**Interfaces:**
- Consumes: `cartometa.extract.maps_links.load_cache/save_cache/resolve_maps_url` (existants), `cartometa.models.MetaRecord`.
- Produces:
  - `find_page(input_dir: Path, slug: str, rmrg: bool = False) -> Path` — lève `FileNotFoundError` (aucun candidat) ou `ValueError` (plusieurs).
  - `would_hit_network(url: str, cache: dict, retry_failed: bool) -> bool`
  - `project_relative_path(html_path: Path, input_dir: Path, raw: str) -> str | None` — `None` si le fichier n'existe pas.
  - `resolve_meta_links(metas: list[MetaRecord], cache_path: Path, resolve: bool, retry_failed: bool, request_delay: float, sleep: Callable[[float], None]) -> None` — mute `meta.maps_latlon`, charge et sauve toujours le cache.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_extract_common.py` :

```python
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
```

Note : le dernier assert suppose que `resolve_maps_url` renvoie la valeur du cache telle quelle (liste JSON → tuple ou liste selon l'implémentation existante). Vérifier dans `cartometa/extract/maps_links.py` ce que renvoie un hit de cache et ajuster l'assert (`== (1.0, 2.0)` ou `== [1.0, 2.0]`) AVANT de lancer le test — l'intention est « la valeur du cache, sans réseau ».

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `uv run pytest tests/test_extract_common.py -v`
Expected: FAIL à l'import — `ModuleNotFoundError: No module named 'cartometa.extract.common'`

- [ ] **Step 3: Écrire `cartometa/extract/common.py`**

Contenu — `find_page` reprend le corps de `cli._find_page` (docstring incluse) avec le filtre RMRG en plus ; `would_hit_network` reprend `cli._would_hit_network` :

```python
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from cartometa.extract.maps_links import load_cache, resolve_maps_url, save_cache
from cartometa.models import MetaRecord

# Both extractors save their pages in the same input/ directory; the RMRG page
# titles all carry the site name ("Bangladesh GeoGuessr Guide - RMRG"), which is
# what lets each extractor find its own save for the same country.
RMRG_MARKER = "rmrg"


def _normalize(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def find_page(input_dir: Path, slug: str, rmrg: bool = False) -> Path:
    """Find the saved .htm for a country, for one source.

    The comparison ignores case and separators: the URL slug is written
    "south-africa" while the browser saves "South Africa — Plonk It.htm". Without
    that normalisation, every country whose name is several words long would be
    unfindable.

    `rmrg` selects the source: the RMRG save for Bangladesh ("Bangladesh
    GeoGuessr Guide - RMRG") also contains the slug, so without this filter the
    Plonk It lookup would become ambiguous the moment both saves exist.

    Raises an explicit error if there is no candidate, or if several files match
    (e.g. a name collision from a second browser save, of the "Poland — Plonk It
    (1).htm" kind): better to fail loudly than to pick one silently.
    """
    target = _normalize(slug)
    pages = sorted(input_dir.glob("*.htm*"))
    candidates = [
        p for p in pages
        if target in _normalize(p.stem)
        and (RMRG_MARKER in _normalize(p.stem).split()) == rmrg
    ]
    if not candidates:
        available = ", ".join(p.name for p in pages) or "none"
        raise FileNotFoundError(
            f"no saved page for '{slug}' in {input_dir}. "
            f"Pages present: {available}"
        )
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise ValueError(
            f"several saved pages match '{slug}' in {input_dir}: "
            f"{names} - delete the duplicates or rename to remove the ambiguity"
        )
    return candidates[0]


def would_hit_network(url: str, cache: dict, retry_failed: bool) -> bool:
    """True if resolving `url` with these settings would really hit the network."""
    if url not in cache:
        return True
    return retry_failed and cache[url] is None


def project_relative_path(html_path: Path, input_dir: Path, raw: str) -> str | None:
    """Resolve a src relative to the saved page into a project-root-relative
    path with forward slashes, or None when the file does not exist on disk."""
    candidate = html_path.parent / raw
    if not candidate.exists():
        return None
    return str(candidate.relative_to(input_dir.parent)).replace("\\", "/")


def resolve_meta_links(
    metas: list[MetaRecord],
    cache_path: Path,
    resolve: bool,
    retry_failed: bool,
    request_delay: float,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Fill in `maps_latlon` for every meta that has a `maps_url`.

    `retry_failed`: by default, a link already recorded as failed (`null` in the
    cache) is never retried — the historical behaviour. Passing `True` replays
    those failures only (already resolved links are never hit over the network
    again).

    `request_delay`: pause in seconds before each real network call, to stay
    polite towards Google when replaying several links. Has no effect on links
    already in the cache (neither successes nor failures that are not retried).

    The cache is loaded and saved even when `resolve` is False, exactly like the
    historical inline loop.
    """
    cache = load_cache(cache_path)
    if resolve:
        for meta in metas:
            if not meta.maps_url:
                continue
            if request_delay > 0 and would_hit_network(meta.maps_url, cache, retry_failed):
                sleep(request_delay)
            meta.maps_latlon = resolve_maps_url(meta.maps_url, cache, retry_failed=retry_failed)
    save_cache(cache_path, cache)
```

ATTENTION au filtre : `RMRG_MARKER in _normalize(p.stem).split()` teste le mot entier « rmrg » (la normalisation transforme « ...Guide - RMRG » en « ...guide rmrg ») — un pays dont le nom contiendrait la sous-chaîne « rmrg » ne serait pas piégé.

- [ ] **Step 4: Adapter `cartometa/extract/cli.py`**

1. Remplacer l'import maps_links et ajouter common :
```python
from cartometa.extract.common import find_page, project_relative_path, resolve_meta_links
```
(supprimer `from cartometa.extract.maps_links import load_cache, resolve_maps_url, save_cache` devenu inutile dans cli.py)
2. Supprimer les fonctions `_find_page` et `_would_hit_network` (déménagées).
3. Dans `run_extract`, remplacer le corps entre le parse et le tri par :

```python
    slug = base_url.rstrip("/").rsplit("/", 1)[-1]
    html_path = find_page(input_dir, slug)
    metas, anomalies = parse_page(html_path.read_text("utf-8", errors="replace"), country, base_url)

    for meta in metas:
        meta.category = infer_category(meta.title, meta.description)
        if meta.image:
            resolved = project_relative_path(html_path, input_dir, meta.image)
            if resolved is None:
                anomalies.append(f"block {meta.id}: image not found ({meta.image})")
            meta.image = resolved

    resolve_meta_links(
        metas, data_dir / "cache" / "maps_links.json",
        resolve=resolve, retry_failed=retry_failed,
        request_delay=request_delay, sleep=sleep,
    )
    metas.sort(key=lambda m: m.id)
```

Le reste de `run_extract` (écriture du JSON, résumé) ne change pas. Noter l'équivalence exacte : `meta.image = resolved` couvre les deux branches (None quand absent, chemin sinon), comme avant.

- [ ] **Step 5: Adapter `tests/test_cli.py`**

1. Ligne 7 : `from cartometa.extract.cli import _find_page, run_extract` → `from cartometa.extract.cli import run_extract`.
2. Supprimer les quatre tests de `_find_page` (déménagés et couverts dans `tests/test_extract_common.py`) : `test_find_page_matches_single_candidate`, `test_find_page_raises_on_ambiguous_candidates`, `test_page_found_despite_the_slug_dashes`, `test_a_missing_page_lists_the_available_pages`.
3. Dans `test_run_extract_does_not_retry_cached_failure_by_default`, la cible du monkeypatch change (la boucle vit désormais dans common) :
```python
    monkeypatch.setattr(
        "cartometa.extract.common.resolve_maps_url",
        lambda url, cache, retry_failed=False: calls.append((url, retry_failed)) or None,
    )
```

- [ ] **Step 6: Lancer toute la suite**

Run: `uv run pytest -v`
Expected: PASS partout (les tests `real_data` peuvent être skippés, c'est normal).

- [ ] **Step 7: Commit**

```bash
git add cartometa/extract/common.py cartometa/extract/cli.py tests/test_extract_common.py tests/test_cli.py
git commit -m "refactor: les briques communes des extracteurs quittent la CLI Plonk It"
```

---

### Task 2: Modèle et parser RMRG (`cartometa/extract/rmrg.py`)

**Files:**
- Modify: `cartometa/models.py` (constante `ORIGIN_RMRG`, champ `overlay`)
- Create: `cartometa/extract/rmrg.py`
- Create: `tests/test_rmrg_parser.py`

**Interfaces:**
- Consumes: `cartometa.extract.html_parser.MAPS_RE` et `_clean_text` (mêmes règles de texte que Plonk It), `cartometa.models.MetaRecord/TIER_REGIONAL/ORIGIN_RMRG`, `cartometa.extract.categories.FALLBACK`.
- Produces:
  - `models.ORIGIN_RMRG = "rmrg"` ; `MetaRecord.overlay: str | None = None` (dernier champ, présent dans `to_dict()`).
  - `parse_rmrg_page(html: str, country: str, base_url: str) -> tuple[list[MetaRecord], list[str]]` — `image` et `overlay` contiennent les src bruts décodés (relatifs à la page), la CLI les résoudra sur disque.
  - `title_from_slug(slug: str) -> str`
  - `SECTION_CATEGORIES: dict[str, str]`

- [ ] **Step 1: Ajouter `ORIGIN_RMRG` et `overlay` dans `cartometa/models.py`**

Après `ORIGIN_MANUAL = "manual"` :
```python
ORIGIN_RMRG = "rmrg"
```
Dans `MetaRecord`, après `maps_latlon` :
```python
    # RMRG only: the guide's region mini-map (SVG), shown next to the photo in
    # the review UI. Never published by the site build.
    overlay: str | None = None
```

- [ ] **Step 2: Écrire les tests du parser qui échouent**

Créer `tests/test_rmrg_parser.py`. Le fragment reproduit la structure réelle relevée le 2026-08-06 (sections, sous-sections h4, image-link, base-image, svg-overlay) :

```python
from __future__ import annotations

from cartometa.extract.rmrg import SECTION_CATEGORIES, parse_rmrg_page, title_from_slug
from cartometa.models import ORIGIN_RMRG, TIER_REGIONAL

BASE_URL = "https://rmrg.me/bangladesh/"

PAGE = """
<div class="category-section" id="landscape-section">
  <div class="category-header"><h3 class="category-title">Landscape</h3></div>
  <div class="meta-list">
    <div class="meta-item" id="landscape/water-plots1" data-item-slug="water-plots1">
      <div class="meta-image-wrapper">
        <a href="https://maps.app.goo.gl/dkf3fRftJGQCvMet9" target="_blank" class="image-link">
          <div class="image-with-overlay">
            <div class="base-image"><img src="Files/water-plots1_8PNy.webp" alt=""></div>
            <div class="svg-overlay-container"><img src="Files/water-plots1_8PNy.svg" class="svg-overlay"></div>
          </div>
        </a>
      </div>
      <div class="meta-content"><div class="meta-description">In the <strong>far south</strong>,
        roads run through   <strong>water plots</strong>.</div></div>
    </div>
  </div>
</div>
<div class="category-section" id="agriculture-section">
  <div class="category-header"><h3 class="category-title">Agriculture</h3></div>
  <div class="meta-list">
    <div class="meta-item" id="agriculture/betel-farms" data-item-slug="betel-farms">
      <div class="meta-image-wrapper">
        <div class="base-image"><img src="Files/betel-farms_8PNy.webp" alt=""></div>
      </div>
      <div class="meta-content"><div class="meta-description">Betel leaf farms, with a
        <a href="https://maps.app.goo.gl/AAAABBBBCCCCDDDD">good example here</a>.</div></div>
    </div>
  </div>
</div>
<div class="category-section" id="architecture-section">
  <div class="category-header"><h3 class="category-title">Architecture</h3></div>
  <div class="subcategory-section" id="architecture-wood-frames-section">
    <h4 class="subcategory-title">Wood Frames</h4>
    <div class="meta-list">
      <div class="meta-item" id="architecture/wood-frames/wood-frame-houses" data-item-slug="wood-frame-houses">
        <div class="meta-content"><div class="meta-description">Wood frame houses.</div></div>
      </div>
    </div>
  </div>
</div>
<div class="learnable-maps-section">
  <div class="learnable-maps-header"><h3 class="learnable-maps-title">Learnable Meta Maps</h3></div>
</div>
"""


def test_metas_carry_the_rmrg_identity():
    metas, anomalies = parse_rmrg_page(PAGE, "BD", BASE_URL)
    assert anomalies == []
    assert [m.id for m in metas] == [
        "landscape/water-plots1",
        "agriculture/betel-farms",
        "architecture/wood-frames/wood-frame-houses",
    ]
    first = metas[0]
    assert first.country == "BD"
    assert first.tier == TIER_REGIONAL
    assert first.origin == ORIGIN_RMRG
    assert first.source_url == "https://rmrg.me/bangladesh/#landscape/water-plots1"


def test_category_comes_from_the_section_heading():
    metas, _ = parse_rmrg_page(PAGE, "BD", BASE_URL)
    by_id = {m.id: m for m in metas}
    assert by_id["landscape/water-plots1"].category == "landscape"
    # Agriculture files under vegetation: the taxonomy has no agriculture pill.
    assert by_id["agriculture/betel-farms"].category == "vegetation"
    # A meta inside an h4 subsection still belongs to its h3 section.
    assert by_id["architecture/wood-frames/wood-frame-houses"].category == "architecture"


def test_unknown_section_falls_back_with_an_anomaly():
    page = PAGE.replace(">Landscape<", ">Wildlife<")
    metas, anomalies = parse_rmrg_page(page, "BD", BASE_URL)
    assert metas[0].category == "autre"
    assert any("wildlife" in a.lower() for a in anomalies)


def test_title_is_the_humanised_slug():
    assert title_from_slug("water-plots1") == "Water plots"
    assert title_from_slug("alternating-brick-corners") == "Alternating brick corners"
    metas, _ = parse_rmrg_page(PAGE, "BD", BASE_URL)
    assert metas[0].title == "Water plots"


def test_description_text_is_normalised():
    metas, _ = parse_rmrg_page(PAGE, "BD", BASE_URL)
    assert metas[0].description == "In the far south, roads run through water plots."


def test_maps_url_prefers_the_image_link_then_falls_back_to_the_text():
    metas, _ = parse_rmrg_page(PAGE, "BD", BASE_URL)
    by_id = {m.id: m for m in metas}
    assert by_id["landscape/water-plots1"].maps_url == "https://maps.app.goo.gl/dkf3fRftJGQCvMet9"
    # No image-link on this block: the maps link inside the description is used.
    assert by_id["agriculture/betel-farms"].maps_url == "https://maps.app.goo.gl/AAAABBBBCCCCDDDD"
    assert by_id["architecture/wood-frames/wood-frame-houses"].maps_url is None


def test_image_and_overlay_are_the_raw_decoded_srcs():
    metas, _ = parse_rmrg_page(PAGE, "BD", BASE_URL)
    by_id = {m.id: m for m in metas}
    assert by_id["landscape/water-plots1"].image == "Files/water-plots1_8PNy.webp"
    assert by_id["landscape/water-plots1"].overlay == "Files/water-plots1_8PNy.svg"
    assert by_id["agriculture/betel-farms"].overlay is None
    assert by_id["architecture/wood-frames/wood-frame-houses"].image is None


def test_block_without_description_is_skipped_with_an_anomaly():
    page = PAGE.replace(
        '<div class="meta-content"><div class="meta-description">Wood frame houses.</div></div>',
        "",
    )
    metas, anomalies = parse_rmrg_page(page, "BD", BASE_URL)
    assert [m.id for m in metas] == ["landscape/water-plots1", "agriculture/betel-farms"]
    assert any("wood-frame-houses" in a for a in anomalies)


def test_section_mapping_covers_the_six_known_sections():
    assert SECTION_CATEGORIES == {
        "landscape": "landscape",
        "agriculture": "vegetation",
        "vegetation": "vegetation",
        "architecture": "architecture",
        "infrastructure": "infrastructure",
        "culture": "culture",
    }
```

- [ ] **Step 3: Vérifier que les tests échouent**

Run: `uv run pytest tests/test_rmrg_parser.py -v`
Expected: FAIL à l'import — `ModuleNotFoundError: No module named 'cartometa.extract.rmrg'`

- [ ] **Step 4: Écrire `cartometa/extract/rmrg.py`**

```python
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import unquote

from selectolax.parser import HTMLParser

from cartometa.extract.categories import FALLBACK
from cartometa.extract.html_parser import MAPS_RE, _clean_text
from cartometa.models import MetaRecord, ORIGIN_RMRG, TIER_REGIONAL

# RMRG sections -> Cartometa taxonomy. Agriculture files under vegetation (the
# taxonomy has no agriculture pill, the spec folds farming into vegetation);
# the other five map 1:1. An unknown section falls back to `autre` with an
# anomaly: RMRG may add sections, and half-classified is better than dropped.
SECTION_CATEGORIES = {
    "landscape": "landscape",
    "agriculture": "vegetation",
    "vegetation": "vegetation",
    "architecture": "architecture",
    "infrastructure": "infrastructure",
    "culture": "culture",
}

_TRAILING_DIGITS_RE = re.compile(r"\d+$")


def title_from_slug(slug: str) -> str:
    """`water-plots1` -> "Water plots": the RMRG slugs are descriptive names
    chosen by the authors, shorter and more stable than a first sentence. The
    trailing digits only disambiguate several photos of the same clue."""
    text = " ".join(_TRAILING_DIGITS_RE.sub("", slug).replace("-", " ").replace("_", " ").split())
    return text[:1].upper() + text[1:]


def _maps_link(item) -> str | None:
    """The image-link href when it is a Maps link, else the first Maps link
    anywhere in the block (some metas only link Maps from their description)."""
    image_link = item.css_first("a.image-link")
    if image_link is not None:
        href = image_link.attributes.get("href")
        if href and MAPS_RE.match(href):
            return href
    return next(
        (a.attributes.get("href") for a in item.css("a")
         if a.attributes.get("href") and MAPS_RE.match(a.attributes["href"])),
        None,
    )


def _src(item, selector: str) -> str | None:
    node = item.css_first(selector)
    if node is None:
        return None
    src = node.attributes.get("src")
    return unquote(src) if src else None


def parse_rmrg_page(html: str, country: str, base_url: str) -> tuple[list[MetaRecord], list[str]]:
    """The RMRG counterpart of `parse_page`: one MetaRecord per `.meta-item`.

    `image` and `overlay` hold the raw decoded srcs, relative to the saved
    page — resolving them against the disk is the CLI's job, like Plonk It.
    """
    tree = HTMLParser(html)
    now = datetime.now(timezone.utc).isoformat()
    metas: list[MetaRecord] = []
    anomalies: list[str] = []

    for section in tree.css("div.category-section"):
        heading = section.css_first("h3.category-title")
        name = _clean_text(heading).lower() if heading is not None else ""
        category = SECTION_CATEGORIES.get(name)
        if category is None:
            anomalies.append(
                f"section '{name}': not in the known taxonomy, metas filed under '{FALLBACK}'"
            )
            category = FALLBACK

        for item in section.css("div.meta-item"):
            block_id = item.attributes.get("id")
            if not block_id:
                anomalies.append(f"section '{name}': meta-item without id, skipped")
                continue
            description_node = item.css_first("div.meta-description")
            if description_node is None:
                anomalies.append(f"block {block_id}: description missing, skipped")
                continue
            slug = item.attributes.get("data-item-slug") or block_id.rsplit("/", 1)[-1]
            description = _clean_text(description_node)
            metas.append(MetaRecord(
                id=block_id,
                country=country,
                tier=TIER_REGIONAL,
                title=title_from_slug(slug),
                description=description,
                category=category,
                source_url=f"{base_url}#{block_id}",
                extracted_at=now,
                origin=ORIGIN_RMRG,
                image=_src(item, ".base-image img"),
                maps_url=_maps_link(item),
                overlay=_src(item, ".svg-overlay-container img"),
            ))
    return metas, anomalies
```

- [ ] **Step 5: Vérifier que les tests passent**

Run: `uv run pytest tests/test_rmrg_parser.py -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Lancer toute la suite**

Run: `uv run pytest -v`
Expected: PASS — en particulier `tests/test_store.py` et `tests/test_build_dataset.py` inchangés (le champ `overlay` par défaut à None ne casse pas `to_dict`).

- [ ] **Step 7: Commit**

```bash
git add cartometa/models.py cartometa/extract/rmrg.py tests/test_rmrg_parser.py
git commit -m "feat: parser RMRG - categorie par section, titre par slug, overlay"
```

---

### Task 3: Overlay SVG — décompression en sidecar

**Files:**
- Modify: `cartometa/extract/rmrg.py` (fonction `prepare_overlay`)
- Modify: `tests/test_rmrg_parser.py` (tests de `prepare_overlay`)

**Interfaces:**
- Produces: `prepare_overlay(svg_path: Path) -> Path | None` — chemin d'un SVG lisible par navigateur (sidecar `.extracted.svg` si l'original est gzippé, l'original s'il est déjà en clair), `None` si illisible. Ne modifie JAMAIS le fichier d'origine.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_rmrg_parser.py` :

```python
import gzip
from pathlib import Path

from cartometa.extract.rmrg import prepare_overlay

SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'


def test_prepare_overlay_decompresses_gzipped_svg_to_a_sidecar(tmp_path: Path):
    """The browser saves the .svgz response body as-is under a .svg name: served
    locally it would not render. The readable copy is a sibling, the original
    save is never touched (it cannot be regenerated from the repo)."""
    original = tmp_path / "water-plots1_8PNy.svg"
    original.write_bytes(gzip.compress(SVG))
    before = original.read_bytes()

    readable = prepare_overlay(original)

    assert readable == tmp_path / "water-plots1_8PNy.extracted.svg"
    assert readable.read_bytes() == SVG
    assert original.read_bytes() == before


def test_prepare_overlay_returns_plain_svg_untouched(tmp_path: Path):
    original = tmp_path / "plain.svg"
    original.write_bytes(b"  \n" + SVG)
    assert prepare_overlay(original) == original
    assert list(tmp_path.iterdir()) == [original]


def test_prepare_overlay_rejects_unreadable_content(tmp_path: Path):
    # Neither gzip nor SVG (e.g. an HTML error page saved in place of the file).
    junk = tmp_path / "junk.svg"
    junk.write_bytes(b"\x00\x01\x02 not an svg")
    assert prepare_overlay(junk) is None

    truncated = tmp_path / "truncated.svg"
    truncated.write_bytes(b"\x1f\x8b\x08\x00 truncated gzip stream")
    assert prepare_overlay(truncated) is None


def test_prepare_overlay_is_idempotent(tmp_path: Path):
    original = tmp_path / "water-plots1_8PNy.svg"
    original.write_bytes(gzip.compress(SVG))
    first = prepare_overlay(original)
    second = prepare_overlay(original)
    assert first == second
    assert second.read_bytes() == SVG
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `uv run pytest tests/test_rmrg_parser.py -v -k prepare_overlay`
Expected: FAIL — `ImportError: cannot import name 'prepare_overlay'`

- [ ] **Step 3: Implémenter `prepare_overlay` dans `cartometa/extract/rmrg.py`**

Ajouter `import gzip` et `from pathlib import Path` en tête, puis :

```python
GZIP_MAGIC = b"\x1f\x8b"


def prepare_overlay(svg_path: Path) -> Path | None:
    """A browser-readable path for a saved RMRG overlay.

    The site serves .svgz bodies that the browser stores as-is under a .svg
    name: gzip bytes, unusable when re-served locally without the
    Content-Encoding header. Those are decompressed into an `.extracted.svg`
    sibling — the original is part of the browser save, not regenerable from
    the repository, and is never modified. A plain-text SVG is referenced
    as-is. Returns None when the content is neither (caller records the
    anomaly)."""
    try:
        data = svg_path.read_bytes()
    except OSError:
        return None
    if data[:2] == GZIP_MAGIC:
        try:
            payload = gzip.decompress(data)
        except OSError:  # gzip.BadGzipFile and EOFError both derive from OSError
            return None
        sidecar = svg_path.with_name(svg_path.stem + ".extracted.svg")
        sidecar.write_bytes(payload)
        return sidecar
    if data.lstrip()[:1] == b"<":
        return svg_path
    return None
```

ATTENTION : `EOFError` (flux gzip tronqué) ne dérive PAS de `OSError` — vérifier pendant l'implémentation et attraper `(OSError, EOFError)` si le test `truncated` échoue.

- [ ] **Step 4: Vérifier que les tests passent**

Run: `uv run pytest tests/test_rmrg_parser.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add cartometa/extract/rmrg.py tests/test_rmrg_parser.py
git commit -m "feat: les overlays svgz de RMRG sont decompresses en sidecars lisibles"
```

---

### Task 4: CLI `cartometa-extract-rmrg`

**Files:**
- Create: `cartometa/extract/rmrg_cli.py`
- Create: `tests/test_rmrg_cli.py`
- Modify: `pyproject.toml` (entrée console)

**Interfaces:**
- Consumes: `find_page(..., rmrg=True)`, `project_relative_path`, `resolve_meta_links` (Task 1) ; `parse_rmrg_page`, `prepare_overlay` (Tasks 2-3) ; `resolve_country` (existant, `cartometa.extract.cli`).
- Produces:
  - `run_extract_rmrg(input_dir: Path, data_dir: Path, country: str, slug: str, resolve: bool = True, retry_failed: bool = False, request_delay: float = 0.0, sleep=time.sleep) -> dict` — écrit `data/metas/<CC>-rmrg.json`, renvoie un résumé `{country, total, by_category, without_image, without_latlon, without_overlay, anomalies, output}`.
  - Entrée console `cartometa-extract-rmrg` → `cartometa.extract.rmrg_cli:main`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_rmrg_cli.py` :

```python
from __future__ import annotations

import gzip
import json
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

    summary = run_extract_rmrg(input_dir, data_dir, "BD", "bangladesh", resolve=False)

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

    summary = run_extract_rmrg(input_dir, data_dir, "BD", "bangladesh", resolve=False)

    metas = json.loads((data_dir / "metas" / "BD-rmrg.json").read_text("utf-8"))
    ghost = metas[0]
    assert ghost["image"] is None
    assert ghost["overlay"] is None
    assert summary["without_image"] == 1
    assert summary["by_category"] == {"landscape": 2}
    assert any("landscape/ghost" in a for a in summary["anomalies"])


def test_run_extract_rmrg_uses_the_shared_maps_cache(tmp_path: Path):
    input_dir = _write_save(tmp_path)
    data_dir = tmp_path / "data"
    cache_path = data_dir / "cache" / "maps_links.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps({"https://maps.app.goo.gl/dkf3fRftJGQCvMet9": [23.5, 90.1]}), "utf-8")

    run_extract_rmrg(input_dir, data_dir, "BD", "bangladesh")

    metas = json.loads((data_dir / "metas" / "BD-rmrg.json").read_text("utf-8"))
    assert metas[1]["maps_latlon"] == [23.5, 90.1]
```

Même remarque que Task 1 sur la valeur cache (tuple vs liste après round-trip JSON) : ici on lit le JSON écrit, donc `[23.5, 90.1]` est correct.

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `uv run pytest tests/test_rmrg_cli.py -v`
Expected: FAIL à l'import — `ModuleNotFoundError: No module named 'cartometa.extract.rmrg_cli'`

- [ ] **Step 3: Écrire `cartometa/extract/rmrg_cli.py`**

```python
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Callable

from cartometa.extract.cli import resolve_country
from cartometa.extract.common import find_page, project_relative_path, resolve_meta_links
from cartometa.extract.rmrg import parse_rmrg_page, prepare_overlay

BASE_URL = "https://rmrg.me"


def run_extract_rmrg(
    input_dir: Path,
    data_dir: Path,
    country: str,
    slug: str,
    resolve: bool = True,
    retry_failed: bool = False,
    request_delay: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """The RMRG counterpart of `run_extract`, writing `<CC>-rmrg.json`.

    A separate file, not a merge into `<CC>.json`: each extractor owns its
    output, so re-running either source can never erase the other's metas.
    """
    base_url = f"{BASE_URL}/{slug}/"
    html_path = find_page(input_dir, slug, rmrg=True)
    metas, anomalies = parse_rmrg_page(
        html_path.read_text("utf-8", errors="replace"), country, base_url
    )

    for meta in metas:
        if meta.image:
            resolved = project_relative_path(html_path, input_dir, meta.image)
            if resolved is None:
                anomalies.append(f"block {meta.id}: image not found ({meta.image})")
            meta.image = resolved
        if meta.overlay:
            candidate = html_path.parent / meta.overlay
            readable = prepare_overlay(candidate) if candidate.exists() else None
            if readable is None:
                anomalies.append(f"block {meta.id}: unreadable overlay ({meta.overlay})")
                meta.overlay = None
            else:
                meta.overlay = str(readable.relative_to(input_dir.parent)).replace("\\", "/")

    resolve_meta_links(
        metas, data_dir / "cache" / "maps_links.json",
        resolve=resolve, retry_failed=retry_failed,
        request_delay=request_delay, sleep=sleep,
    )
    metas.sort(key=lambda m: m.id)

    out_path = data_dir / "metas" / f"{country}-rmrg.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([m.to_dict() for m in metas], indent=2, ensure_ascii=False), "utf-8"
    )

    by_category: dict[str, int] = {}
    for meta in metas:
        by_category[meta.category] = by_category.get(meta.category, 0) + 1
    return {
        "country": country,
        "total": len(metas),
        "by_category": by_category,
        "without_image": sum(1 for m in metas if not m.image),
        "without_latlon": sum(1 for m in metas if m.maps_latlon is None),
        "without_overlay": sum(1 for m in metas if not m.overlay),
        "anomalies": anomalies,
        "output": str(out_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extracts the metas from a saved RMRG guide")
    parser.add_argument("slug", help="country, e.g. bangladesh")
    parser.add_argument("--input", type=Path, default=Path("input"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument(
        "--country",
        help="ISO alpha-2 code, if the slug cannot be derived from a Natural Earth name.",
    )
    parser.add_argument("--no-resolve", action="store_true", help="do not resolve the Maps links")
    parser.add_argument(
        "--retry-failed-links",
        action="store_true",
        help=(
            "Replays the Maps links recorded as failed (null in the cache) - by "
            "default, a cached failure is never retried. Already resolved links are "
            "never hit over the network again."
        ),
    )
    parser.add_argument(
        "--link-delay",
        type=float,
        default=1.5,
        help="Pause in seconds before each real network call to resolve a link (polite towards Google).",
    )
    args = parser.parse_args()

    country = args.country.upper() if args.country else resolve_country(args.slug, args.data / "cache")
    summary = run_extract_rmrg(
        args.input, args.data, country, args.slug,
        resolve=not args.no_resolve,
        retry_failed=args.retry_failed_links,
        request_delay=args.link_delay,
    )

    print(f"{summary['country']}: {summary['total']} metas {summary['by_category']}")
    print(
        f"  without image: {summary['without_image']}   "
        f"without coordinates: {summary['without_latlon']}   "
        f"without overlay: {summary['without_overlay']}"
    )
    for anomaly in summary["anomalies"]:
        print(f"  anomaly: {anomaly}")
    print(f"  written: {summary['output']}")
```

Différence voulue avec la CLI Plonk It : `slug` est obligatoire (pas de pays par défaut évident côté RMRG).

- [ ] **Step 4: Déclarer l'entrée console dans `pyproject.toml`**

Dans `[project.scripts]`, après `cartometa-extract` :
```toml
cartometa-extract-rmrg = "cartometa.extract.rmrg_cli:main"
```

- [ ] **Step 5: Vérifier que les tests passent**

Run: `uv run pytest tests/test_rmrg_cli.py -v`
Expected: PASS (3 tests). `uv run` resynchronise l'environnement, donc la nouvelle entrée console sera installée au passage.

- [ ] **Step 6: Lancer toute la suite**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add cartometa/extract/rmrg_cli.py tests/test_rmrg_cli.py pyproject.toml uv.lock
git commit -m "feat: cartometa-extract-rmrg ecrit data/metas/<CC>-rmrg.json"
```

(Si `uv.lock` n'a pas bougé, le retirer du `git add`.)

---

### Task 5: Stockage — `load_metas` à trois fichiers, `overlay` dans la queue

**Files:**
- Modify: `cartometa/review/store.py` (propriété `rmrg_metas`, `load_metas`, `_image_url` → `_relative_url`, `build_queue`)
- Modify: `tests/test_store.py` (nouveaux tests)

**Interfaces:**
- Consumes: `CountryPaths` existant.
- Produces:
  - `CountryPaths.rmrg_metas -> Path` = `data/metas/<CC>-rmrg.json`
  - `load_metas(paths)` = importé + rmrg + manuel, dans cet ordre.
  - Items de `build_queue` : nouvelle clé `"overlay"` (`"/" + chemin` ou `None`), même convention que `"image"`.

- [ ] **Step 1: Écrire les tests qui échouent**

Regarder d'abord comment `tests/test_store.py` fabrique ses fixtures (helpers existants pour écrire metas/geo) et suivre le même style. Ajouter :

```python
def test_load_metas_reads_imported_then_rmrg_then_manual(tmp_path):
    paths = CountryPaths(tmp_path, "BD")
    paths.imported_metas.parent.mkdir(parents=True)
    paths.imported_metas.write_text(json.dumps([{"id": "plonk-1"}]), "utf-8")
    paths.rmrg_metas.write_text(json.dumps([{"id": "landscape/water-plots1"}]), "utf-8")
    paths.manual_metas.parent.mkdir(parents=True)
    paths.manual_metas.write_text(json.dumps([{"id": "man-1"}]), "utf-8")

    assert [m["id"] for m in load_metas(paths)] == [
        "plonk-1", "landscape/water-plots1", "man-1",
    ]


def test_load_metas_without_rmrg_file_behaves_as_before(tmp_path):
    paths = CountryPaths(tmp_path, "BD")
    paths.imported_metas.parent.mkdir(parents=True)
    paths.imported_metas.write_text(json.dumps([{"id": "plonk-1"}]), "utf-8")

    assert [m["id"] for m in load_metas(paths)] == ["plonk-1"]


def test_build_queue_exposes_the_overlay_like_the_image(tmp_path):
    paths = CountryPaths(tmp_path, "BD")
    paths.imported_metas.parent.mkdir(parents=True)
    paths.imported_metas.write_text(json.dumps([
        {"id": "landscape/water-plots1", "title": "Water plots", "description": "d",
         "category": "landscape", "tier": "regional", "origin": "rmrg",
         "image": "input/save_files/water-plots1.webp",
         "overlay": "input/save_files/water-plots1.extracted.svg",
         "source_url": "https://rmrg.me/bangladesh/#landscape/water-plots1"},
        {"id": "plonk-1", "title": "t", "description": "d",
         "category": "autre", "tier": "regional"},
    ]), "utf-8")

    queue = build_queue(paths)
    items = {item["id"]: item for item in queue["items"]}
    assert items["landscape/water-plots1"]["overlay"] == "/input/save_files/water-plots1.extracted.svg"
    # A meta without the key (every Plonk It and manual meta) exposes None.
    assert items["plonk-1"]["overlay"] is None
```

Adapter les imports en tête de test_store.py si `build_queue`/`load_metas`/`CountryPaths` n'y sont pas déjà importés.

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `uv run pytest tests/test_store.py -v -k "rmrg or overlay"`
Expected: FAIL — `AttributeError: 'CountryPaths' object has no attribute 'rmrg_metas'`, et KeyError `'overlay'`.

- [ ] **Step 3: Implémenter dans `cartometa/review/store.py`**

1. Dans `CountryPaths`, après `imported_metas` :
```python
    @property
    def rmrg_metas(self) -> Path:
        return self.data / "metas" / f"{self.country}-rmrg.json"
```
2. Mettre à jour la docstring de `CountryPaths` (« Two sources of metas coexist » → trois : Plonk It, RMRG, manuel — les deux imports gitignorés car régénérables, le manuel versionné).
3. `load_metas` :
```python
def load_metas(paths: CountryPaths) -> list[dict]:
    """Imported metas (Plonk It then RMRG) then manual ones, in that order."""
    return (
        read_json_list(paths.imported_metas)
        + read_json_list(paths.rmrg_metas)
        + read_json_list(paths.manual_metas)
    )
```
4. Généraliser `_image_url` :
```python
def _relative_url(path: str | None) -> str | None:
    # Both sources store a path relative to the project root, which the server
    # serves as-is.
    return "/" + path if path else None
```
5. Dans `build_queue`, remplacer `"image": _image_url(meta),` par :
```python
            "image": _relative_url(meta.get("image")),
            "overlay": _relative_url(meta.get("overlay")),
```
6. Vérifier qu'aucun autre appel à `_image_url` ne subsiste (`grep -n "_image_url" cartometa/`).

- [ ] **Step 4: Vérifier que les tests passent**

Run: `uv run pytest tests/test_store.py tests/test_review_server.py -v`
Expected: PASS

- [ ] **Step 5: Lancer toute la suite**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add cartometa/review/store.py tests/test_store.py
git commit -m "feat: load_metas lit le fichier rmrg et la queue expose l'overlay"
```

---

### Task 6: Viewer de revue — afficher la mini-carte RMRG

**Files:**
- Modify: `cartometa/review/static/index.html` (deuxième `<img>` dans `#source`)
- Modify: `cartometa/review/static/app.js` (affichage conditionnel)

**Interfaces:**
- Consumes: `item.overlay` (URL `"/input/..."` ou `null`/absent) fourni par `/api/queue` (Task 5).
- Produces: rien pour les tâches suivantes (feuille de l'arbre).

Pas de harnais de test JS dans ce projet : la vérification est visuelle, à la Task 7 (extraction réelle + serveur). Les changements sont minimaux et symétriques du traitement de `image`.

- [ ] **Step 1: `index.html` — le deuxième `<img>`**

Ligne 52, remplacer :
```html
    <div id="source"><img id="image" alt=""></div>
```
par :
```html
    <div id="source"><img id="image" alt=""><img id="overlay" alt="" hidden></div>
```
La règle CSS existante `#source img { width: 100%; border: 1px solid #ccc; }` s'applique aux deux.

- [ ] **Step 2: `app.js` — affichage conditionnel**

Dans `render()`, branche « queue vide » (après la ligne `document.getElementById('image').removeAttribute('src');`) :
```js
    document.getElementById('overlay').removeAttribute('src');
    document.getElementById('overlay').hidden = true;
```
Branche normale, après `if (item.image) ... else ...` :
```js
  const overlay = document.getElementById('overlay');
  // RMRG only: the guide's own region mini-map, i.e. the answer being traced.
  if (item.overlay) { overlay.src = item.overlay; overlay.hidden = false; }
  else { overlay.removeAttribute('src'); overlay.hidden = true; }
```
Note : les métas manuelles construites côté JS (ligne ~258, `image: meta.image || null`) n'ont pas de clé `overlay` — `item.overlay` y est `undefined`, donc la branche else s'applique, rien à changer.

- [ ] **Step 3: Vérifier la suite (le serveur sert les statiques tels quels)**

Run: `uv run pytest tests/test_review_server.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add cartometa/review/static/index.html cartometa/review/static/app.js
git commit -m "feat: la revue affiche la mini-carte rmrg a cote de la photo"
```

---

### Task 7: Extraction réelle du Bangladesh et vérification de bout en bout

**Files:**
- Aucun fichier versionné : produit `data/metas/BD-rmrg.json` (gitignoré) et les sidecars `input/**/*.extracted.svg` (gitignorés).

**Interfaces:**
- Consumes: tout ce qui précède.

- [ ] **Step 1: Extraction sans réseau d'abord**

Run: `uv run cartometa-extract-rmrg bangladesh --no-resolve`
Expected: `BD: 112 metas {...}` — 112 métas, réparties sur landscape/vegetation/architecture/infrastructure/culture (agriculture fondue dans vegetation), zéro ou très peu d'anomalies, `without_image: 0`, `without_overlay: 0`. Vérifier que `data/metas/BD.json` (Plonk It) n'a pas bougé : `git status` ne le montre pas (gitignoré) donc vérifier par date de modification (`ls -l data/metas/BD.json`).

Si le compte n'est pas 112 ou que des anomalies inattendues sortent : STOP, diagnostiquer sur la vraie page avant de continuer (superpowers:systematic-debugging).

- [ ] **Step 2: Extraction avec résolution des liens**

Run: `uv run cartometa-extract-rmrg bangladesh`
Expected: ~112 liens résolus (≈3 min avec le délai de politesse de 1,5 s), `without_latlon` proche de 0. Les liens déjà en cache ne repartent pas sur le réseau.

- [ ] **Step 3: Vérifier la queue de revue**

Précaution (mémoire projet) : vérifier qu'aucun serveur de revue ne tourne déjà, et utiliser un port explicite hors 8765 (AnkiConnect) :

Run: `uv run cartometa-review BD --port 8799` puis ouvrir `http://127.0.0.1:8799`.
Expected: la queue montre les métas RMRG (les 44 Plonk It sont toutes décidées), la photo ET la mini-carte s'affichent, le lien source pointe vers `https://rmrg.me/bangladesh/#...`. Arrêter le serveur après vérification.

- [ ] **Step 4: Suite complète une dernière fois**

Run: `uv run pytest -v`
Expected: PASS — y compris les tests `real_data` maintenant que `data/geo/` existe localement.

- [ ] **Step 5: Rien à committer pour les données**

`git status` doit être propre (données gitignorées). Si un fichier de données apparaît, NE PAS l'ajouter — comprendre pourquoi avant.
