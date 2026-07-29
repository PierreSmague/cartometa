# Cartometa — Plan d'implémentation (verticale Pologne)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer la chaîne complète — extraction, géométries, revue, viewer — sur la Pologne de bout en bout, et mesurer le taux de validation automatique qui décidera de la suite.

**Architecture:** Trois étages communiquant par fichiers. Un extracteur lit les pages sauvegardées à la main dans `input/` et produit `data/metas/PL.json`. Un pipeline géométrique détecte la silhouette du pays dans l'encart cartographique, en dérive une calibration pixel→WGS84 par pays, puis vectorise les zones rouges en `data/geo/PL.geojson`. Une interface de revue au clavier valide les géométries, un viewer statique les consulte.

**Tech Stack:** Python 3.14, `uv`, `selectolax`, `Pillow`, `numpy`, `scipy`, `scikit-image`, `shapely`, `pytest`. Viewer et interface de revue en HTML/JS statique avec Leaflet, sans étape de build.

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-07-28-cartometa-design.md`.
- **Aucun crawler.** Le code ne requête jamais `plonkit.net`. Seul accès réseau autorisé : résolution des liens courts Google Maps, et téléchargement unique de Natural Earth. Les deux sont mis en cache sur disque.
- `input/` n'est jamais versionné. Les tests unitaires utilisent des images **synthétiques** générées en code ; les tests sur images réelles sont marqués `@pytest.mark.real_data` et sautés si `input/` est absent.
- Tout seuil, tolérance ou couleur vit dans `config/defaults.toml`, jamais en constante dans le code.
- Le viewer est déployable par simple copie de dossier : pas de serveur applicatif, pas de base de données, pas de build.
- Cible de précision : **10 km**. En cas d'incertitude, un polygone légèrement trop large vaut mieux qu'un trop étroit.
- Python 3.14.6 et `uv` 0.11.30 sont installés, et l'ensemble des dépendances a été vérifié comme installable en roues binaires sur 3.14 le 2026-07-28. Aucun repli sur 3.12 n'est nécessaire.

### Constantes mesurées sur données réelles

Relevées le 2026-07-28 sur six images de la page Pologne. Elles servent de valeurs par défaut dans `config/defaults.toml`, et sont ajustables.

| Constante | Valeur | Origine |
|---|---|---|
| Crème de remplissage du pays | RGB `(255, 253, 235)`, tolérance ±8 | identique sur toutes les images |
| Rouge de zone et de pin | RGB ≈ `(193, 40, 58)` — **H≈352°, S≈0,79, V≈0,76** | quatre images, écart max 3° de teinte |
| Seuils du masque rouge | H ∈ [340°, 365°] (wrap), S > 0,45, V > 0,35 | encadre la mesure avec marge |
| Encart, image 1920×943 | bbox ≈ x[1380–1908] y[438–931] | invariant d'échelle (0,719 × largeur) |
| Surface minimale de silhouette | 2 % de l'image | `Poland-bollard` donne 0,03 % → pas d'encart |

---

## Structure de fichiers

```
pyproject.toml                  dépendances et commandes
config/defaults.toml            tous les seuils
cartometa/
  models.py                     MetaRecord, GeoRecord — types partagés
  config.py                     chargement TOML + surcharges
  extract/
    html_parser.py              page sauvegardée → MetaRecord
    maps_links.py               résolution des liens courts + cache
    categories.py               inférence de catégorie
    cli.py                      commande `extract`
  geo/
    reference.py                Natural Earth : téléchargement, cache, contour pays
    silhouette.py               détection de la silhouette et de l'encart
    calibrate.py                ajustement pixel → WGS84
    redmask.py                  masque rouge, à l'intérieur de la silhouette
    vectorize.py                contours → shapely → GeoJSON valide
    confidence.py               score et avertissements
    cli.py                      commande `build-geo`
  review/
    server.py                   serveur local stdlib, persistance atomique
    static/index.html           écran de revue
    static/app.js               logique clavier et carte
viewer/
  index.html                    viewer public
  app.js                        index bbox + point-dans-polygone
  style.css
tests/
  fixtures.py                   générateurs d'images synthétiques
  test_html_parser.py
  test_maps_links.py
  test_categories.py
  test_silhouette.py
  test_calibrate.py
  test_redmask.py
  test_vectorize.py
  test_confidence.py
  test_real_data.py             marqués real_data, sautés sans input/
```

Découpage par responsabilité, pas par couche technique : chaque module du pipeline correspond à un stage isolément testable.

---

### Task 1: Squelette du projet, configuration et fixtures

**Files:**
- Create: `pyproject.toml`, `config/defaults.toml`, `cartometa/__init__.py`, `cartometa/config.py`, `cartometa/models.py`
- Create: `tests/fixtures.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: rien
- Produces: `load_config(path: Path | None = None) -> Config` ; `Config.get(dotted_key: str, default=None)` ; dataclasses `MetaRecord` et `GeoRecord` ; `tests.fixtures.synthetic_meta_image(...) -> PIL.Image.Image`

- [ ] **Step 1: Créer le projet et installer les dépendances**

```bash
cd C:/Users/Smaguy/Documents/Scripts/Cartometa
uv init --bare --python 3.14
uv add selectolax pillow numpy scipy scikit-image shapely
uv add --dev pytest
```

- [ ] **Step 2: Écrire `config/defaults.toml` avec les constantes mesurées**

```toml
[cream]
rgb = [255, 253, 235]
tolerance = 8

[red]
hue_min = 340.0
hue_max = 365.0
saturation_min = 0.45
value_min = 0.35

[silhouette]
min_area_fraction = 0.02
closing_size = 9
min_component_px = 1000

[calibration]
min_iou = 0.90

[vectorize]
min_component_px = 40
simplify_tolerance_px = 1.5
outward_buffer_km = 3.0

[spot]
default_radius_km = 25.0
radius_by_category = { vegetation = 50.0, autre = 25.0 }

[paths]
input = "input"
data = "data"
```

- [ ] **Step 3: Écrire le test de chargement de configuration**

```python
# tests/test_config.py
from cartometa.config import load_config

def test_load_config_reads_measured_constants():
    cfg = load_config()
    assert cfg.get("cream.rgb") == [255, 253, 235]
    assert cfg.get("red.hue_min") == 340.0
    assert cfg.get("silhouette.min_area_fraction") == 0.02

def test_get_returns_default_for_missing_key():
    cfg = load_config()
    assert cfg.get("nope.absent", 7) == 7
```

- [ ] **Step 4: Lancer le test, vérifier qu'il échoue**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'cartometa.config'`

- [ ] **Step 5: Écrire `cartometa/config.py`**

```python
from __future__ import annotations
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "defaults.toml"


@dataclass(frozen=True)
class Config:
    data: dict[str, Any]

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def load_config(path: Path | None = None) -> Config:
    with open(path or DEFAULT_CONFIG, "rb") as handle:
        return Config(tomllib.load(handle))
```

- [ ] **Step 6: Écrire `cartometa/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

TIER_COUNTRY = "country"
TIER_REGIONAL = "regional"
TIER_SPOT = "spot"


@dataclass
class MetaRecord:
    id: str
    country: str
    tier: str
    title: str
    description: str
    category: str
    source_url: str
    extracted_at: str
    description_origin: str = "imported"
    image: str | None = None
    maps_url: str | None = None
    maps_latlon: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GeoRecord:
    id: str
    geometry: dict[str, Any]
    confidence: float
    warnings: list[str] = field(default_factory=list)
    status: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

- [ ] **Step 7: Écrire `tests/fixtures.py`, générateur d'images synthétiques**

Ces fixtures reproduisent le template mesuré : silhouette crème dans la portion droite, zone rouge éventuelle, photo bruitée à gauche contenant du rouge parasite.

```python
from __future__ import annotations
import numpy as np
from PIL import Image, ImageDraw

CREAM = (255, 253, 235, 255)
RED = (193, 40, 58, 255)


def synthetic_meta_image(
    size: tuple[int, int] = (1920, 943),
    with_inset: bool = True,
    red_shape: str | None = "zone",
    parasite_red: bool = True,
) -> Image.Image:
    """Reproduit le template Plonk It mesuré.

    red_shape: "zone" (ellipse dans la silhouette), "pin" (petit blob), None.
    """
    w, h = size
    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # Photo a gauche : bruit opaque, avec du rouge parasite façon rose des vents.
    photo_w = int(w * 0.872)
    rng = np.random.default_rng(0)
    noise = rng.integers(60, 200, size=(h, photo_w, 3), dtype=np.uint8)
    alpha = np.full((h, photo_w, 1), 255, dtype=np.uint8)
    img.paste(Image.fromarray(np.concatenate([noise, alpha], axis=2), "RGBA"), (0, 0))
    if parasite_red:
        draw.ellipse([60, h - 200, 200, h - 60], fill=RED)

    if not with_inset:
        return img

    # Encart : silhouette crème rectangulaire aux coordonnées relatives mesurées.
    x0, x1 = int(w * 0.719), int(w * 0.994)
    y0, y1 = int(h * 0.464), int(h * 0.987)
    draw.rectangle([x0, y0, x1, y1], fill=CREAM)

    if red_shape == "zone":
        draw.ellipse(
            [x0 + (x1 - x0) // 4, y0 + (y1 - y0) // 2, x0 + (x1 - x0) // 2, y1 - 20],
            fill=RED,
        )
    elif red_shape == "pin":
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        draw.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=RED)
    return img
```

- [ ] **Step 8: Lancer les tests, vérifier qu'ils passent**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, 2 tests

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock config cartometa tests
git commit -m "feat: squelette du projet, config mesurée et fixtures synthétiques"
```

---

### Task 2: Parsing d'une page sauvegardée

**Files:**
- Create: `cartometa/extract/__init__.py`, `cartometa/extract/html_parser.py`
- Create: `tests/test_html_parser.py`

**Interfaces:**
- Consumes: `MetaRecord`, `TIER_*` de `cartometa.models`
- Produces: `parse_page(html: str, country: str, base_url: str) -> tuple[list[MetaRecord], list[str]]` — retourne les métas et la liste des anomalies rencontrées. La catégorie est laissée à `"autre"` et les chemins d'image sont **relatifs à la page**, résolus par la CLI en Task 4.

- [ ] **Step 1: Écrire les tests**

Le typage par tier vient du `<h3>` précédent. Le titre est le `<strong>`, la description le texte complet du `<p>`. L'image retenue est la plus large du `srcset`.

```python
# tests/test_html_parser.py
from cartometa.extract.html_parser import parse_page

PAGE = """
<h1>Poland</h1>
<h3>Step 1 - Identifying Poland</h3>
<div id="AAAA" class="relative group/bk">
  <img srcset="f/bollard_006.webp 450w, f/bollard_005.webp 1920w" src="f/bollard_006.webp">
  <p><strong>Bollards</strong> are white with a red stripe.</p>
</div>
<h3>Step 2 - Regional and voivodeship-specific clues</h3>
<div id="1VXO" class="relative group/bk">
  <a href="https://maps.app.goo.gl/JmGQh1"><img srcset="f/orchards_004.webp 600w, f/orchards_005.webp 1920w"></a>
  <p><strong>Orchards</strong> are mostly concentrated around Grojec.</p>
</div>
<h3>Step 3 - Spotlight</h3>
<div id="TATR" class="relative group/bk">
  <a href="https://goo.gl/maps/axmv3M"><img srcset="f/tatra_002.webp 1200w"></a>
  <p><strong>Tatra Mountains</strong> are visible in the far south.</p>
</div>
<h3>Step 4 - Maps and resources</h3>
<div id="ZZZZ" class="relative group/bk"><p><strong>Links</strong> here.</p></div>
"""


def test_parses_one_record_per_tip_block_ignoring_step_4():
    metas, anomalies = parse_page(PAGE, "PL", "https://www.plonkit.net/poland")
    assert [m.id for m in metas] == ["AAAA", "1VXO", "TATR"]
    assert anomalies == []


def test_tier_comes_from_preceding_heading():
    metas, _ = parse_page(PAGE, "PL", "https://www.plonkit.net/poland")
    assert {m.id: m.tier for m in metas} == {
        "AAAA": "country", "1VXO": "regional", "TATR": "spot",
    }


def test_title_is_strong_and_description_is_full_paragraph():
    metas, _ = parse_page(PAGE, "PL", "https://www.plonkit.net/poland")
    orchards = next(m for m in metas if m.id == "1VXO")
    assert orchards.title == "Orchards"
    assert orchards.description == "Orchards are mostly concentrated around Grojec."


def test_selects_widest_srcset_variant():
    metas, _ = parse_page(PAGE, "PL", "https://www.plonkit.net/poland")
    assert next(m for m in metas if m.id == "1VXO").image == "f/orchards_005.webp"
    assert next(m for m in metas if m.id == "AAAA").image == "f/bollard_005.webp"


def test_captures_maps_url_and_builds_anchored_source_url():
    metas, _ = parse_page(PAGE, "PL", "https://www.plonkit.net/poland")
    tatra = next(m for m in metas if m.id == "TATR")
    assert tatra.maps_url == "https://goo.gl/maps/axmv3M"
    assert tatra.source_url == "https://www.plonkit.net/poland#TATR"
    assert next(m for m in metas if m.id == "AAAA").maps_url is None


def test_block_without_strong_is_reported_as_anomaly_not_crash():
    html = '<h3>Step 2 - Regional</h3><div id="BAD" class="relative group/bk"><p>no strong</p></div>'
    metas, anomalies = parse_page(html, "PL", "https://x/poland")
    assert metas == []
    assert any("BAD" in a for a in anomalies)
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/test_html_parser.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'cartometa.extract'`

- [ ] **Step 3: Écrire `cartometa/extract/html_parser.py`**

```python
from __future__ import annotations
import re
from datetime import datetime, timezone
from urllib.parse import unquote
from selectolax.parser import HTMLParser
from cartometa.models import MetaRecord, TIER_COUNTRY, TIER_REGIONAL, TIER_SPOT

TIER_BY_STEP = {"1": TIER_COUNTRY, "2": TIER_REGIONAL, "3": TIER_SPOT}
STEP_RE = re.compile(r"step\s*(\d)", re.IGNORECASE)
MAPS_RE = re.compile(r"^https://(maps\.app\.goo\.gl|goo\.gl/maps)/", re.IGNORECASE)


def _widest_srcset(node) -> str | None:
    """Retient l'URL de plus grande largeur déclarée, sinon le src."""
    srcset = node.attributes.get("srcset")
    if srcset:
        best, best_w = None, -1
        for candidate in srcset.split(","):
            parts = candidate.strip().split()
            if len(parts) == 2 and parts[1].endswith("w"):
                width = int(parts[1][:-1])
                if width > best_w:
                    best, best_w = parts[0], width
        if best:
            return unquote(best)
    src = node.attributes.get("src")
    return unquote(src) if src else None


def parse_page(html: str, country: str, base_url: str) -> tuple[list[MetaRecord], list[str]]:
    tree = HTMLParser(html)
    now = datetime.now(timezone.utc).isoformat()
    metas: list[MetaRecord] = []
    anomalies: list[str] = []
    current_tier: str | None = None

    for node in tree.css("h3, div"):
        if node.tag == "h3":
            match = STEP_RE.search(node.text(strip=True))
            current_tier = TIER_BY_STEP.get(match.group(1)) if match else None
            continue

        classes = node.attributes.get("class") or ""
        block_id = node.attributes.get("id")
        if "group/bk" not in classes or not block_id:
            continue
        if current_tier is None:
            continue  # Step 4 et hors-section : ignorés volontairement

        strong = node.css_first("strong")
        paragraph = node.css_first("p")
        if strong is None or paragraph is None:
            anomalies.append(f"bloc {block_id}: titre ou description absent, ignoré")
            continue

        image_node = node.css_first("img")
        link = next(
            (a.attributes.get("href") for a in node.css("a")
             if a.attributes.get("href") and MAPS_RE.match(a.attributes["href"])),
            None,
        )

        metas.append(MetaRecord(
            id=block_id,
            country=country,
            tier=current_tier,
            title=strong.text(strip=True),
            description=paragraph.text(strip=True),
            category="autre",
            source_url=f"{base_url}#{block_id}",
            extracted_at=now,
            image=_widest_srcset(image_node) if image_node is not None else None,
            maps_url=link,
        ))
    return metas, anomalies
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `uv run pytest tests/test_html_parser.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add cartometa/extract tests/test_html_parser.py
git commit -m "feat: parsing des pages sauvegardées avec typage par section"
```

---

### Task 3: Résolution des liens Google Maps

**Files:**
- Create: `cartometa/extract/maps_links.py`
- Create: `tests/test_maps_links.py`

**Interfaces:**
- Consumes: rien
- Produces: `resolve_maps_url(url: str, cache: dict[str, Any], opener=None) -> tuple[float, float] | None` ; `load_cache(path: Path) -> dict` ; `save_cache(path: Path, cache: dict) -> None`

Les coordonnées sont lues **dans l'URL de redirection**, sans charger la page cible. Vérifié : `goo.gl/maps/axmv3MroqEJsr5rk6` → `.../@49.302333,20.0088885,3a,...`.

- [ ] **Step 1: Écrire les tests**

`opener` est injecté pour que les tests n'atteignent jamais le réseau.

```python
# tests/test_maps_links.py
from cartometa.extract.maps_links import resolve_maps_url, extract_latlon

REDIRECT = "https://www.google.com/maps/@49.302333,20.0088885,3a,45.1y,155.29h,90.27t,0.33r/data=!3m6"


def test_extract_latlon_from_redirect_url():
    assert extract_latlon(REDIRECT) == (49.302333, 20.0088885)


def test_extract_latlon_returns_none_when_absent():
    assert extract_latlon("https://www.google.com/maps/place/Krakow") is None


def test_resolve_uses_redirect_location_without_fetching_target():
    calls = []

    def opener(url):
        calls.append(url)
        return REDIRECT

    cache = {}
    assert resolve_maps_url("https://goo.gl/maps/abc", cache, opener) == (49.302333, 20.0088885)
    assert calls == ["https://goo.gl/maps/abc"]


def test_resolve_is_cached_and_hits_network_once():
    calls = []

    def opener(url):
        calls.append(url)
        return REDIRECT

    cache = {}
    resolve_maps_url("https://goo.gl/maps/abc", cache, opener)
    resolve_maps_url("https://goo.gl/maps/abc", cache, opener)
    assert len(calls) == 1


def test_unresolvable_link_is_cached_as_null_and_returns_none():
    def opener(url):
        raise OSError("timeout")

    cache = {}
    assert resolve_maps_url("https://goo.gl/maps/dead", cache, opener) is None
    assert cache["https://goo.gl/maps/dead"] is None
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/test_maps_links.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire `cartometa/extract/maps_links.py`**

```python
from __future__ import annotations
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable

LATLON_RE = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+)")
USER_AGENT = "cartometa/0.1 (usage personnel)"


def extract_latlon(url: str) -> tuple[float, float] | None:
    match = LATLON_RE.search(url)
    return (float(match.group(1)), float(match.group(2))) if match else None


def _default_opener(url: str) -> str:
    """Retourne l'URL finale après redirections, sans lire le corps."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.geturl()


def resolve_maps_url(
    url: str, cache: dict[str, Any], opener: Callable[[str], str] | None = None
) -> tuple[float, float] | None:
    if url in cache:
        value = cache[url]
        return tuple(value) if value else None
    try:
        final_url = (opener or _default_opener)(url)
        latlon = extract_latlon(final_url)
    except OSError:
        latlon = None
    cache[url] = list(latlon) if latlon else None
    return latlon


def load_cache(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def save_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), "utf-8")
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `uv run pytest tests/test_maps_links.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add cartometa/extract/maps_links.py tests/test_maps_links.py
git commit -m "feat: résolution en cache des liens Maps courts"
```

---

### Task 4: Inférence de catégorie et commande `extract`

**Files:**
- Create: `cartometa/extract/categories.py`, `cartometa/extract/cli.py`
- Create: `tests/test_categories.py`
- Modify: `pyproject.toml` (entrée `[project.scripts]`)

**Interfaces:**
- Consumes: `parse_page`, `resolve_maps_url`, `load_cache`, `save_cache`, `MetaRecord`
- Produces: `infer_category(title: str, description: str) -> str` ; `run_extract(input_dir: Path, data_dir: Path, country: str, base_url: str, resolve: bool = True) -> dict` retournant le résumé d'exécution. Écrit `data/metas/<CC>.json`.

- [ ] **Step 1: Écrire les tests de catégorie**

```python
# tests/test_categories.py
import pytest
from cartometa.extract.categories import infer_category


@pytest.mark.parametrize("text,expected", [
    ("Bollards are white with a red stripe", "bollards"),
    ("Utility poles have a yellow band", "poteaux"),
    ("The Google car is a white Subaru", "vehicule"),
    ("Orchards are concentrated around Grojec", "vegetation"),
    ("Direction signs are yellow", "signalisation"),
    ("Something entirely unrelated", "autre"),
])
def test_infer_category(text, expected):
    assert infer_category(text, "") == expected


def test_title_takes_precedence_over_description():
    assert infer_category("Bollards", "seen near many trees and orchards") == "bollards"
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/test_categories.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire `cartometa/extract/categories.py`**

```python
from __future__ import annotations

# L'ordre compte : la première catégorie dont un mot-clé apparaît l'emporte.
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("bollards", ("bollard",)),
    ("poteaux", ("pole", "poles", "utility pole", "power line", "pylon")),
    ("vehicule", ("google car", "camera", "rift", "snorkel", "car blur", "subaru")),
    ("vegetation", ("orchard", "forest", "tree", "trees", "vegetation", "crop", "field")),
    ("signalisation", ("sign", "signs", "signal", "marking", "road line", "chevron", "guardrail")),
]


def infer_category(title: str, description: str) -> str:
    for haystack in (title.lower(), description.lower()):
        for category, words in KEYWORDS:
            if any(word in haystack for word in words):
                return category
    return "autre"
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `uv run pytest tests/test_categories.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Écrire `cartometa/extract/cli.py`**

`run_extract` est idempotent : il réécrit intégralement `data/metas/<CC>.json` à partir de `input/`, triant par `id`.

```python
from __future__ import annotations
import argparse
import json
from pathlib import Path

from cartometa.extract.categories import infer_category
from cartometa.extract.html_parser import parse_page
from cartometa.extract.maps_links import load_cache, resolve_maps_url, save_cache

COUNTRY_BY_SLUG = {"poland": ("PL", "https://www.plonkit.net/poland")}


def _find_page(input_dir: Path, slug: str) -> tuple[Path, Path]:
    """Retrouve le .htm sauvegardé et son dossier _files pour un pays."""
    for html_path in sorted(input_dir.glob("*.htm*")):
        if slug in html_path.stem.lower():
            assets = html_path.with_name(html_path.stem + "_files")
            return html_path, assets
    raise FileNotFoundError(f"aucune page sauvegardée pour '{slug}' dans {input_dir}")


def run_extract(
    input_dir: Path, data_dir: Path, country: str, base_url: str, resolve: bool = True
) -> dict:
    slug = base_url.rstrip("/").rsplit("/", 1)[-1]
    html_path, assets_dir = _find_page(input_dir, slug)
    metas, anomalies = parse_page(html_path.read_text("utf-8", errors="replace"), country, base_url)

    cache_path = data_dir / "cache" / "maps_links.json"
    cache = load_cache(cache_path)

    for meta in metas:
        meta.category = infer_category(meta.title, meta.description)
        if meta.image:
            candidate = html_path.parent / meta.image
            if candidate.exists():
                meta.image = str(candidate.relative_to(input_dir.parent)).replace("\\", "/")
            else:
                anomalies.append(f"bloc {meta.id}: image introuvable ({meta.image})")
                meta.image = None
        if resolve and meta.maps_url:
            meta.maps_latlon = resolve_maps_url(meta.maps_url, cache)

    save_cache(cache_path, cache)
    metas.sort(key=lambda m: m.id)

    out_path = data_dir / "metas" / f"{country}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([m.to_dict() for m in metas], indent=2, ensure_ascii=False), "utf-8"
    )

    by_tier: dict[str, int] = {}
    for meta in metas:
        by_tier[meta.tier] = by_tier.get(meta.tier, 0) + 1
    return {
        "country": country,
        "total": len(metas),
        "by_tier": by_tier,
        "without_image": sum(1 for m in metas if not m.image),
        "without_latlon": sum(1 for m in metas if m.maps_latlon is None),
        "anomalies": anomalies,
        "output": str(out_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrait les métas des pages sauvegardées")
    parser.add_argument("slug", nargs="?", default="poland", help="pays, ex. poland")
    parser.add_argument("--input", type=Path, default=Path("input"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--no-resolve", action="store_true", help="ne pas résoudre les liens Maps")
    args = parser.parse_args()

    country, base_url = COUNTRY_BY_SLUG[args.slug]
    summary = run_extract(args.input, args.data, country, base_url, resolve=not args.no_resolve)

    print(f"{summary['country']}: {summary['total']} métas {summary['by_tier']}")
    print(f"  sans image: {summary['without_image']}   sans coordonnées: {summary['without_latlon']}")
    for anomaly in summary["anomalies"]:
        print(f"  anomalie: {anomaly}")
    print(f"  écrit: {summary['output']}")
```

- [ ] **Step 6: Déclarer les commandes dans `pyproject.toml`**

```toml
[project.scripts]
cartometa-extract = "cartometa.extract.cli:main"
cartometa-geo = "cartometa.geo.cli:main"
cartometa-review = "cartometa.review.server:main"
```

- [ ] **Step 7: Lancer l'extraction sur les données réelles**

Run: `uv run cartometa-extract poland`
Expected: environ 38 métas, réparties sur les trois tiers, `data/metas/PL.json` écrit. Vérifier que `by_tier` contient bien les trois clés et qu'aucune anomalie bloquante n'apparaît.

- [ ] **Step 8: Vérifier l'idempotence**

```bash
uv run cartometa-extract poland && cp data/metas/PL.json /tmp/first.json
uv run cartometa-extract poland && diff /tmp/first.json data/metas/PL.json
```

Expected: seule la ligne `extracted_at` diffère. Si d'autres champs bougent, corriger avant de continuer.

- [ ] **Step 9: Commit**

```bash
git add cartometa/extract pyproject.toml tests/test_categories.py
git commit -m "feat: commande extract avec catégories et résumé d'exécution"
```

---

### Task 5: Référentiel Natural Earth

**Files:**
- Create: `cartometa/geo/__init__.py`, `cartometa/geo/reference.py`
- Create: `tests/test_reference.py`

**Interfaces:**
- Consumes: rien
- Produces: `country_geometry(iso_a2: str, cache_dir: Path) -> shapely.geometry.base.BaseGeometry` ; `ensure_dataset(cache_dir: Path) -> Path`

URL vérifiée le 2026-07-28, HTTP 200 : `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson`. Domaine public. Téléchargée une seule fois dans `data/cache/`.

- [ ] **Step 1: Écrire les tests**

```python
# tests/test_reference.py
import json
import pytest
from shapely.geometry import shape
from cartometa.geo.reference import country_geometry

FAKE = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"ISO_A2": "PL", "ISO_A2_EH": "PL", "NAME": "Poland"},
     "geometry": {"type": "Polygon", "coordinates": [[[14.0, 49.0], [24.0, 49.0], [24.0, 55.0], [14.0, 55.0], [14.0, 49.0]]]}}]}


@pytest.fixture
def cache_dir(tmp_path):
    (tmp_path / "ne_10m_admin_0_countries.geojson").write_text(json.dumps(FAKE), "utf-8")
    return tmp_path


def test_country_geometry_returns_shapely_geometry(cache_dir):
    geom = country_geometry("PL", cache_dir)
    assert geom.is_valid
    assert geom.bounds == (14.0, 49.0, 24.0, 55.0)


def test_unknown_country_raises(cache_dir):
    with pytest.raises(KeyError):
        country_geometry("ZZ", cache_dir)
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/test_reference.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire `cartometa/geo/reference.py`**

```python
from __future__ import annotations
import json
import urllib.request
from functools import lru_cache
from pathlib import Path

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

DATASET_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_admin_0_countries.geojson"
)
DATASET_NAME = "ne_10m_admin_0_countries.geojson"


def ensure_dataset(cache_dir: Path) -> Path:
    path = cache_dir / DATASET_NAME
    if not path.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(DATASET_URL, path)
    return path


@lru_cache(maxsize=8)
def _load(path_str: str) -> dict:
    return json.loads(Path(path_str).read_text("utf-8"))


def country_geometry(iso_a2: str, cache_dir: Path) -> BaseGeometry:
    """Contour Natural Earth 1:10m du pays, en WGS84."""
    data = _load(str(ensure_dataset(cache_dir)))
    for feature in data["features"]:
        props = feature["properties"]
        codes = {props.get("ISO_A2"), props.get("ISO_A2_EH")}
        if iso_a2.upper() in codes:
            geom = shape(feature["geometry"])
            return geom if geom.is_valid else geom.buffer(0)
    raise KeyError(f"pays introuvable dans Natural Earth: {iso_a2}")
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `uv run pytest tests/test_reference.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Vérifier le téléchargement réel une fois**

```bash
uv run python -c "from pathlib import Path; from cartometa.geo.reference import country_geometry; g=country_geometry('PL', Path('data/cache')); print(g.geom_type, [round(v,2) for v in g.bounds])"
```

Expected: bornes proches de `[14.12, 49.02, 24.15, 54.84]`. Si elles s'en écartent nettement, le jeu de données n'est pas celui attendu.

- [ ] **Step 6: Commit**

```bash
git add cartometa/geo tests/test_reference.py
git commit -m "feat: référentiel Natural Earth en cache local"
```

---

### Task 6: Détection de la silhouette et de l'encart

**Files:**
- Create: `cartometa/geo/silhouette.py`
- Create: `tests/test_silhouette.py`

**Interfaces:**
- Consumes: `Config`, `tests.fixtures.synthetic_meta_image`
- Produces: dataclass `Inset(bbox: tuple[int, int, int, int], mask: np.ndarray, area_fraction: float)` ; `find_inset(rgba: np.ndarray, cfg: Config) -> Inset | None`

Deux règles issues des mesures, à ne pas simplifier : la silhouette est **`crème ∪ rouge`**, parce que la zone rouge remplace le crème et creuse la forme ; et l'absence de silhouette suffisamment grande signifie « pas d'encart », donc méta nationale.

- [ ] **Step 1: Écrire les tests**

```python
# tests/test_silhouette.py
import numpy as np
from cartometa.config import load_config
from cartometa.geo.silhouette import find_inset
from tests.fixtures import synthetic_meta_image


def _array(**kwargs):
    return np.array(synthetic_meta_image(**kwargs).convert("RGBA"))


def test_finds_inset_at_measured_relative_position():
    inset = find_inset(_array(), load_config())
    assert inset is not None
    x0, y0, x1, y1 = inset.bbox
    assert 0.70 < x0 / 1920 < 0.73
    assert 0.45 < y0 / 943 < 0.48


def test_returns_none_when_no_inset_present():
    assert find_inset(_array(with_inset=False), load_config()) is None


def test_mask_includes_red_zone_so_shape_is_not_hollowed():
    """La zone rouge remplace le crème : sans l'union, la silhouette serait trouée."""
    inset = find_inset(_array(red_shape="zone"), load_config())
    plain = find_inset(_array(red_shape=None), load_config())
    assert abs(inset.area_fraction - plain.area_fraction) < 0.005


def test_parasite_red_in_photo_is_outside_the_mask():
    inset = find_inset(_array(parasite_red=True), load_config())
    x0, _, _, _ = inset.bbox
    assert x0 > 1000  # la rose des vents est à gauche, hors silhouette
    assert not inset.mask[:, :1000].any()


def test_scale_invariance_between_1920_and_800():
    big = find_inset(_array(size=(1920, 943)), load_config())
    small = find_inset(_array(size=(800, 393)), load_config())
    assert abs(big.bbox[0] / 1920 - small.bbox[0] / 800) < 0.02
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/test_silhouette.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire `cartometa/geo/silhouette.py`**

```python
from __future__ import annotations
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import binary_closing, binary_fill_holes
from skimage.measure import label, regionprops

from cartometa.config import Config


@dataclass(frozen=True)
class Inset:
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1
    mask: np.ndarray                 # booléen, pleine taille image
    area_fraction: float


def red_pixels(rgba: np.ndarray, cfg: Config) -> np.ndarray:
    """Masque du rouge de la palette Plonk It, avec wrap-around de la teinte."""
    rgb = rgba[..., :3].astype(np.float64) / 255.0
    alpha = rgba[..., 3]
    maximum = rgb.max(axis=2)
    minimum = rgb.min(axis=2)
    delta = maximum - minimum

    with np.errstate(divide="ignore", invalid="ignore"):
        hue = np.zeros_like(maximum)
        red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        mask_r = (maximum == red) & (delta > 0)
        mask_g = (maximum == green) & (delta > 0)
        mask_b = (maximum == blue) & (delta > 0)
        hue[mask_r] = ((green - blue)[mask_r] / delta[mask_r]) % 6
        hue[mask_g] = ((blue - red)[mask_g] / delta[mask_g]) + 2
        hue[mask_b] = ((red - green)[mask_b] / delta[mask_b]) + 4
        hue = hue * 60.0
        saturation = np.where(maximum > 0, delta / np.maximum(maximum, 1e-9), 0.0)

    hue_min = cfg.get("red.hue_min")
    hue_max = cfg.get("red.hue_max")
    # Wrap-around : [340, 365] couvre 340→360 puis 0→5.
    in_hue = (hue >= hue_min) | (hue <= (hue_max - 360.0))
    return (
        in_hue
        & (saturation >= cfg.get("red.saturation_min"))
        & (maximum >= cfg.get("red.value_min"))
        & (alpha > 200)
    )


def _cream_pixels(rgba: np.ndarray, cfg: Config) -> np.ndarray:
    cream = np.array(cfg.get("cream.rgb"), dtype=np.int64)
    tolerance = cfg.get("cream.tolerance")
    diff = np.abs(rgba[..., :3].astype(np.int64) - cream).max(axis=2)
    return (diff <= tolerance) & (rgba[..., 3] > 200)


def find_inset(rgba: np.ndarray, cfg: Config) -> Inset | None:
    """Localise la silhouette du pays. Retourne None si l'image n'a pas d'encart."""
    height, width = rgba.shape[:2]
    candidate = _cream_pixels(rgba, cfg) | red_pixels(rgba, cfg)

    size = int(cfg.get("silhouette.closing_size"))
    candidate = binary_closing(candidate, np.ones((size, size)))

    labelled = label(candidate)
    regions = [r for r in regionprops(labelled) if r.area >= cfg.get("silhouette.min_component_px")]
    if not regions:
        return None

    largest = max(regions, key=lambda r: r.area)
    area_fraction = largest.area / (width * height)
    if area_fraction < cfg.get("silhouette.min_area_fraction"):
        return None

    mask = binary_fill_holes(labelled == largest.label)
    y0, x0, y1, x1 = largest.bbox
    return Inset(bbox=(x0, y0, x1, y1), mask=mask, area_fraction=area_fraction)
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `uv run pytest tests/test_silhouette.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Vérifier sur les images réelles**

```bash
uv run python -c "
import numpy as np, json
from pathlib import Path
from PIL import Image
from cartometa.config import load_config
from cartometa.geo.silhouette import find_inset
cfg = load_config()
for m in json.loads(Path('data/metas/PL.json').read_text('utf-8')):
    if not m['image']: continue
    inset = find_inset(np.array(Image.open(m['image']).convert('RGBA')), cfg)
    print(f\"{m['tier']:9} {m['title'][:28]:28} {'encart ' + str(inset.bbox) if inset else 'PAS D ENCART'}\")
"
```

Expected: les métas `regional` et `spot` montrent un encart aux coordonnées relatives ~0,72 × largeur ; les métas `country` affichent « PAS D ENCART ». Tout désaccord entre le tier et la présence d'encart est à noter — il devient un avertissement en Task 10.

- [ ] **Step 6: Commit**

```bash
git add cartometa/geo/silhouette.py tests/test_silhouette.py
git commit -m "feat: détection de silhouette par union crème et rouge"
```

---

### Task 7: Calibration pixel → WGS84

**Files:**
- Create: `cartometa/geo/calibrate.py`
- Create: `tests/test_calibrate.py`

**Interfaces:**
- Consumes: `Inset`, `country_geometry`, `Config`
- Produces: dataclass `Calibration(ax, bx, ay, by, iou)` avec `pixel_to_lonlat(x, y) -> tuple[float, float]` et `to_dict()/from_dict()` ; `fit_calibration(mask: np.ndarray, country: BaseGeometry, cfg: Config) -> Calibration` ; `save_calibration(path, calib)` / `load_calibration(path)`

Modèle affine sans rotation : `lon = ax·x + bx`, `lat = ay·y + by` avec `ay < 0`. Sur l'étendue d'un seul pays, ignorer la projection coûte de l'ordre du kilomètre — négligeable devant la cible de 10 km. L'ajustement part de l'alignement des bounding boxes, puis raffine par Nelder-Mead sur l'IoU.

- [ ] **Step 1: Écrire les tests**

```python
# tests/test_calibrate.py
import numpy as np
from shapely.geometry import box
from cartometa.config import load_config
from cartometa.geo.calibrate import Calibration, fit_calibration, load_calibration, save_calibration


def _rect_mask(shape=(400, 400), x0=100, x1=300, y0=50, y1=250):
    mask = np.zeros(shape, dtype=bool)
    mask[y0:y1, x0:x1] = True
    return mask


def test_fit_recovers_transform_for_a_rectangle():
    country = box(14.0, 49.0, 24.0, 55.0)
    calib = fit_calibration(_rect_mask(), country, load_config())
    lon, lat = calib.pixel_to_lonlat(100, 50)
    assert abs(lon - 14.0) < 0.2 and abs(lat - 55.0) < 0.2
    lon, lat = calib.pixel_to_lonlat(300, 250)
    assert abs(lon - 24.0) < 0.2 and abs(lat - 49.0) < 0.2


def test_latitude_axis_is_inverted():
    calib = fit_calibration(_rect_mask(), box(14.0, 49.0, 24.0, 55.0), load_config())
    assert calib.ay < 0


def test_iou_is_high_for_matching_shapes():
    calib = fit_calibration(_rect_mask(), box(14.0, 49.0, 24.0, 55.0), load_config())
    assert calib.iou > 0.95


def test_roundtrip_through_disk(tmp_path):
    calib = Calibration(ax=0.05, bx=14.0, ay=-0.03, by=55.0, iou=0.97)
    path = tmp_path / "PL.json"
    save_calibration(path, calib)
    assert load_calibration(path) == calib
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/test_calibrate.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire `cartometa/geo/calibrate.py`**

```python
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from shapely.geometry.base import BaseGeometry

from cartometa.config import Config

RASTER_SIZE = 220  # grille de comparaison ; assez fin pour l'IoU, assez rapide


@dataclass(frozen=True)
class Calibration:
    ax: float
    bx: float
    ay: float
    by: float
    iou: float

    def pixel_to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        return (self.ax * x + self.bx, self.ay * y + self.by)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Calibration":
        return Calibration(**data)


def _rasterize(geom: BaseGeometry, bounds, size: int) -> np.ndarray:
    """Rasterise une géométrie dans une grille size×size couvrant `bounds`."""
    from shapely.geometry import Point
    from shapely.prepared import prep

    min_lon, min_lat, max_lon, max_lat = bounds
    prepared = prep(geom)
    lons = np.linspace(min_lon, max_lon, size)
    lats = np.linspace(max_lat, min_lat, size)
    grid = np.zeros((size, size), dtype=bool)
    for row, lat in enumerate(lats):
        for col, lon in enumerate(lons):
            grid[row, col] = prepared.contains(Point(lon, lat))
    return grid


def _mask_to_grid(mask: np.ndarray, calib_params, bounds, size: int) -> np.ndarray:
    """Projette le masque pixel dans la même grille géographique."""
    ax, bx, ay, by = calib_params
    min_lon, min_lat, max_lon, max_lat = bounds
    ys, xs = np.nonzero(mask)
    lons = ax * xs + bx
    lats = ay * ys + by
    cols = ((lons - min_lon) / (max_lon - min_lon) * (size - 1)).round().astype(int)
    rows = ((max_lat - lats) / (max_lat - min_lat) * (size - 1)).round().astype(int)
    keep = (cols >= 0) & (cols < size) & (rows >= 0) & (rows < size)
    grid = np.zeros((size, size), dtype=bool)
    grid[rows[keep], cols[keep]] = True
    return grid


def fit_calibration(mask: np.ndarray, country: BaseGeometry, cfg: Config) -> Calibration:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        raise ValueError("silhouette vide, calibration impossible")

    px0, px1 = xs.min(), xs.max()
    py0, py1 = ys.min(), ys.max()
    min_lon, min_lat, max_lon, max_lat = country.bounds

    # Départ : alignement des bounding boxes.
    ax = (max_lon - min_lon) / max(px1 - px0, 1)
    ay = -(max_lat - min_lat) / max(py1 - py0, 1)
    start = np.array([ax, min_lon - ax * px0, ay, max_lat - ay * py0])

    bounds = country.bounds
    target = _rasterize(country, bounds, RASTER_SIZE)

    def negative_iou(params) -> float:
        grid = _mask_to_grid(mask, params, bounds, RASTER_SIZE)
        union = (grid | target).sum()
        return 0.0 if union == 0 else -((grid & target).sum() / union)

    result = minimize(
        negative_iou, start, method="Nelder-Mead",
        options={"xatol": 1e-6, "fatol": 1e-4, "maxiter": 600},
    )
    params = result.x if -result.fun >= -negative_iou(start) else start
    return Calibration(
        ax=float(params[0]), bx=float(params[1]),
        ay=float(params[2]), by=float(params[3]),
        iou=float(-negative_iou(params)),
    )


def save_calibration(path: Path, calib: Calibration) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calib.to_dict(), indent=2), "utf-8")


def load_calibration(path: Path) -> Calibration:
    return Calibration.from_dict(json.loads(path.read_text("utf-8")))
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `uv run pytest tests/test_calibrate.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Calibrer la Pologne sur une image réelle et contrôler l'IoU**

```bash
uv run python -c "
import numpy as np, json
from pathlib import Path
from PIL import Image
from cartometa.config import load_config
from cartometa.geo.silhouette import find_inset
from cartometa.geo.calibrate import fit_calibration, save_calibration
from cartometa.geo.reference import country_geometry
cfg = load_config()
metas = json.loads(Path('data/metas/PL.json').read_text('utf-8'))
meta = next(m for m in metas if m['tier'] == 'spot' and m['image'])
inset = find_inset(np.array(Image.open(meta['image']).convert('RGBA')), cfg)
calib = fit_calibration(inset.mask, country_geometry('PL', Path('data/cache')), cfg)
print('IoU', round(calib.iou, 4), calib)
save_calibration(Path('data/calib/PL.json'), calib)
"
```

Expected: IoU au-dessus de `calibration.min_iou` (0,90). Une méta `spot` est choisie car son pin n'ampute pas la silhouette.

**Si l'IoU reste sous 0,90 :** ne pas contourner. C'est le signal que le modèle affine sans rotation ne suffit pas pour ce pays. Consigner la valeur obtenue, puis essayer dans l'ordre — élargir `maxiter`, puis ajouter un terme de rotation au modèle. Documenter le résultat dans le rapport de Task 12.

- [ ] **Step 6: Vérifier la calibration contre un point connu**

```bash
uv run python -c "
from pathlib import Path
from cartometa.geo.calibrate import load_calibration
c = load_calibration(Path('data/calib/PL.json'))
print('coin haut-gauche ->', c.pixel_to_lonlat(1380, 438))
print('coin bas-droit   ->', c.pixel_to_lonlat(1908, 931))
"
```

Expected: le premier point tombe près de `(14.1, 54.9)`, le second près de `(24.2, 49.0)` — les coins de la bounding box polonaise.

- [ ] **Step 7: Commit**

```bash
git add cartometa/geo/calibrate.py tests/test_calibrate.py data/calib/PL.json
git commit -m "feat: calibration pixel vers WGS84 par ajustement d'IoU"
```

---

### Task 8: Masque rouge et vectorisation

**Files:**
- Create: `cartometa/geo/vectorize.py`
- Create: `tests/test_vectorize.py`

**Interfaces:**
- Consumes: `red_pixels` de `cartometa.geo.silhouette`, `Calibration`, `Config`
- Produces: `zone_mask(rgba, inset, cfg) -> np.ndarray` ; `mask_to_geometry(mask, calib, cfg) -> BaseGeometry | None` ; `buffer_km(geom, km) -> BaseGeometry`

Le rouge n'est retenu que **dans la silhouette** : c'est plus fort qu'un recadrage rectangulaire, et cela élimine par construction le rouge de la photo, mesuré comme atteignant x=0 sur `Poland-southern-hills`.

- [ ] **Step 1: Écrire les tests**

```python
# tests/test_vectorize.py
import numpy as np
from shapely.geometry import Point
from cartometa.config import load_config
from cartometa.geo.calibrate import Calibration
from cartometa.geo.silhouette import find_inset
from cartometa.geo.vectorize import buffer_km, mask_to_geometry, zone_mask
from tests.fixtures import synthetic_meta_image

CALIB = Calibration(ax=0.01, bx=14.0, ay=-0.01, by=55.0, iou=0.99)


def _array(**kwargs):
    return np.array(synthetic_meta_image(**kwargs).convert("RGBA"))


def test_zone_mask_excludes_parasite_red_from_the_photo():
    rgba = _array(red_shape="zone", parasite_red=True)
    inset = find_inset(rgba, load_config())
    mask = zone_mask(rgba, inset, load_config())
    assert mask.any()
    assert not mask[:, :1000].any()  # la rose des vents est écartée


def test_zone_mask_is_empty_when_no_red_zone():
    rgba = _array(red_shape=None, parasite_red=False)
    inset = find_inset(rgba, load_config())
    assert not zone_mask(rgba, inset, load_config()).any()


def test_mask_to_geometry_produces_a_valid_polygon():
    rgba = _array(red_shape="zone")
    inset = find_inset(rgba, load_config())
    geom = mask_to_geometry(zone_mask(rgba, inset, load_config()), CALIB, load_config())
    assert geom is not None
    assert geom.is_valid
    assert geom.geom_type in ("Polygon", "MultiPolygon")


def test_every_ring_is_closed_and_non_self_intersecting():
    rgba = _array(red_shape="zone")
    inset = find_inset(rgba, load_config())
    geom = mask_to_geometry(zone_mask(rgba, inset, load_config()), CALIB, load_config())
    parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    assert parts
    for part in parts:
        assert part.is_valid
        for ring in [part.exterior, *part.interiors]:
            assert ring.is_ring, "anneau non fermé"
            assert ring.is_simple, "anneau auto-intersectant"


def test_mask_to_geometry_returns_none_on_empty_mask():
    assert mask_to_geometry(np.zeros((50, 50), dtype=bool), CALIB, load_config()) is None


def test_buffer_km_grows_the_shape_outward():
    point = Point(19.0, 52.0).buffer(0.1)
    grown = buffer_km(point, 10.0)
    assert grown.area > point.area
    assert grown.contains(point)
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/test_vectorize.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire `cartometa/geo/vectorize.py`**

```python
from __future__ import annotations
import math

import numpy as np
from scipy.ndimage import binary_closing, binary_opening
from shapely.geometry import Polygon, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from skimage.measure import label, regionprops

from cartometa.config import Config
from cartometa.geo.calibrate import Calibration
from cartometa.geo.silhouette import Inset, red_pixels

EARTH_KM_PER_DEGREE = 111.32


def zone_mask(rgba: np.ndarray, inset: Inset, cfg: Config) -> np.ndarray:
    """Rouge retenu uniquement à l'intérieur de la silhouette du pays."""
    mask = red_pixels(rgba, cfg) & inset.mask
    structure = np.ones((3, 3))
    return binary_closing(binary_opening(mask, structure), structure)


def buffer_km(geom: BaseGeometry, km: float) -> BaseGeometry:
    """Dilatation d'environ `km`, en approximant localement le degré."""
    if km <= 0:
        return geom
    centre_lat = geom.centroid.y
    degrees = km / (EARTH_KM_PER_DEGREE * max(math.cos(math.radians(centre_lat)), 0.1))
    return geom.buffer(degrees)


def mask_to_geometry(mask: np.ndarray, calib: Calibration, cfg: Config) -> BaseGeometry | None:
    labelled = label(mask)
    minimum = cfg.get("vectorize.min_component_px")
    tolerance = cfg.get("vectorize.simplify_tolerance_px")

    polygons: list[Polygon] = []
    for region in regionprops(labelled):
        if region.area < minimum:
            continue
        component = labelled == region.label
        # Marching squares sur le masque rembourré, pour fermer les formes au bord.
        from skimage.measure import find_contours

        padded = np.pad(component, 1, constant_values=False)
        for contour in find_contours(padded.astype(float), 0.5):
            if len(contour) < 4:
                continue
            pixels = [(x - 1, y - 1) for y, x in contour]
            ring = [calib.pixel_to_lonlat(x, y) for x, y in pixels]
            polygon = Polygon(ring)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if polygon.is_empty:
                continue
            simplified = polygon.simplify(tolerance * abs(calib.ax), preserve_topology=True)
            if not simplified.is_empty and simplified.area > 0:
                polygons.append(simplified)

    if not polygons:
        return None

    merged = unary_union(polygons)
    if not merged.is_valid:
        merged = merged.buffer(0)
    merged = buffer_km(merged, cfg.get("vectorize.outward_buffer_km"))
    if merged.is_empty:
        return None
    if merged.geom_type == "GeometryCollection":
        parts = [g for g in merged.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        merged = unary_union(parts) if parts else None
    return merged
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `uv run pytest tests/test_vectorize.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add cartometa/geo/vectorize.py tests/test_vectorize.py
git commit -m "feat: masque rouge intra-silhouette et vectorisation valide"
```

---

### Task 9: Score de confiance et avertissements

**Files:**
- Create: `cartometa/geo/confidence.py`
- Create: `tests/test_confidence.py`

**Interfaces:**
- Consumes: `GeoRecord`, `Calibration`
- Produces: `evaluate(geometry, *, tier, calib_iou, latlon, component_count, touches_border, area_fraction_of_country, cfg) -> tuple[float, list[str]]`

Le score n'a qu'un seul rôle : **ordonner la file de revue**, les cas douteux en premier. Les avertissements sont les cas dégénérés listés au §5 de la spec.

- [ ] **Step 1: Écrire les tests**

```python
# tests/test_confidence.py
from shapely.geometry import Point, box
from cartometa.config import load_config
from cartometa.geo.confidence import evaluate

CFG = load_config()
GOOD = box(18.0, 51.0, 20.0, 52.0)


def _evaluate(**overrides):
    kwargs = dict(
        geometry=GOOD, tier="regional", calib_iou=0.97, latlon=(51.5, 19.0),
        component_count=1, touches_border=False, area_fraction_of_country=0.15, cfg=CFG,
    )
    kwargs.update(overrides)
    return evaluate(**kwargs)


def test_clean_case_scores_high_without_warnings():
    score, warnings = _evaluate()
    assert score > 0.8 and warnings == []


def test_maps_point_outside_polygon_is_a_warning_and_lowers_score():
    score, warnings = _evaluate(latlon=(45.0, 5.0))
    assert any("hors du polygone" in w for w in warnings)
    assert score < 0.5


def test_missing_geometry_scores_zero():
    score, warnings = _evaluate(geometry=None)
    assert score == 0.0
    assert any("aucune géométrie" in w for w in warnings)


def test_low_calibration_iou_is_flagged():
    _, warnings = _evaluate(calib_iou=0.60)
    assert any("calibration" in w for w in warnings)


def test_many_components_suggest_parasite_red():
    _, warnings = _evaluate(component_count=9)
    assert any("composantes" in w for w in warnings)


def test_border_touching_zone_is_flagged_as_possibly_truncated():
    _, warnings = _evaluate(touches_border=True)
    assert any("tronquée" in w for w in warnings)


def test_near_national_coverage_suggests_using_country_polygon():
    _, warnings = _evaluate(area_fraction_of_country=0.97)
    assert any("quasi-totalité" in w for w in warnings)
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `uv run pytest tests/test_confidence.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire `cartometa/geo/confidence.py`**

```python
from __future__ import annotations

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from cartometa.config import Config


def evaluate(
    geometry: BaseGeometry | None,
    *,
    tier: str,
    calib_iou: float | None,
    latlon: tuple[float, float] | None,
    component_count: int,
    touches_border: bool,
    area_fraction_of_country: float | None,
    cfg: Config,
) -> tuple[float, list[str]]:
    """Score dans [0, 1] servant uniquement à trier la file de revue."""
    warnings: list[str] = []

    if geometry is None or geometry.is_empty:
        return 0.0, ["aucune géométrie produite"]

    score = 1.0

    if calib_iou is not None and calib_iou < cfg.get("calibration.min_iou"):
        warnings.append(f"calibration faible (IoU {calib_iou:.2f})")
        score -= 0.3

    # Le contrôle le plus fort : le point Maps doit tomber dans le polygone.
    if latlon is not None and tier == "regional":
        if geometry.contains(Point(latlon[1], latlon[0])):
            score += 0.1
        else:
            warnings.append("le point Maps tombe hors du polygone")
            score -= 0.6

    if component_count > 5:
        warnings.append(f"{component_count} composantes disjointes, rouge parasite probable")
        score -= 0.2

    if touches_border:
        warnings.append("zone au bord de l'encart, possiblement tronquée")
        score -= 0.15

    if area_fraction_of_country is not None:
        if area_fraction_of_country > 0.95:
            warnings.append("rouge sur la quasi-totalité du pays, préférer le polygone national")
            score -= 0.25
        elif area_fraction_of_country < 0.002:
            warnings.append("surface très faible, île ou lieu ponctuel")
            score -= 0.1

    return max(0.0, min(1.0, score)), warnings
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `uv run pytest tests/test_confidence.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add cartometa/geo/confidence.py tests/test_confidence.py
git commit -m "feat: score de confiance et détection des cas dégénérés"
```

---

### Task 10: Commande `build-geo` — aiguillage par tier

**Files:**
- Create: `cartometa/geo/cli.py`
- Create: `tests/test_real_data.py`
- Modify: `pyproject.toml` (ajouter le marqueur `real_data`)

**Interfaces:**
- Consumes: tout le paquet `cartometa.geo`, `data/metas/<CC>.json`
- Produces: `build_country(country: str, data_dir: Path, cfg: Config) -> dict` écrivant `data/geo/<CC>.geojson`. **Les statuts de revue déjà présents sont préservés** : une méta `validé` ou `rejeté` n'est jamais réécrite en `auto`.

Aiguillage : `country` → polygone Natural Earth, aucun pixel. `spot` → point du lien Maps, dilaté du rayon de la catégorie. `regional` → silhouette, calibration, masque, vectorisation.

- [ ] **Step 1: Ajouter le marqueur pytest dans `pyproject.toml`**

```toml
[tool.pytest.ini_options]
markers = ["real_data: nécessite input/, sauté si absent"]
```

- [ ] **Step 2: Écrire les tests sur données réelles**

```python
# tests/test_real_data.py
import json
from pathlib import Path
import pytest
from shapely.geometry import shape, Point

pytestmark = pytest.mark.real_data
GEO = Path("data/geo/PL.geojson")
METAS = Path("data/metas/PL.json")


def _skip_unless_built():
    if not GEO.exists() or not METAS.exists():
        pytest.skip("lancer d'abord cartometa-extract puis cartometa-geo")


def test_every_geometry_is_valid():
    _skip_unless_built()
    data = json.loads(GEO.read_text("utf-8"))
    for feature in data["features"]:
        geom = shape(feature["geometry"])
        assert geom.is_valid, f"géométrie invalide: {feature['properties']['id']}"
        assert not geom.is_empty


def test_country_tier_covers_warsaw():
    _skip_unless_built()
    data = json.loads(GEO.read_text("utf-8"))
    metas = {m["id"]: m for m in json.loads(METAS.read_text("utf-8"))}
    warsaw = Point(21.0122, 52.2297)
    national = [f for f in data["features"] if metas[f["properties"]["id"]]["tier"] == "country"]
    assert national, "aucune méta nationale"
    assert all(shape(f["geometry"]).contains(warsaw) for f in national)


def test_no_geometry_covers_a_point_in_the_atlantic():
    _skip_unless_built()
    data = json.loads(GEO.read_text("utf-8"))
    atlantic = Point(-30.0, 40.0)
    assert not any(shape(f["geometry"]).contains(atlantic) for f in data["features"])


def test_regional_geometries_contain_their_maps_point():
    """Mesure objective du taux de justesse — le chiffre qui décide de la suite."""
    _skip_unless_built()
    data = json.loads(GEO.read_text("utf-8"))
    metas = {m["id"]: m for m in json.loads(METAS.read_text("utf-8"))}
    checked, correct = 0, 0
    for feature in data["features"]:
        meta = metas[feature["properties"]["id"]]
        if meta["tier"] != "regional" or not meta["maps_latlon"]:
            continue
        checked += 1
        lat, lon = meta["maps_latlon"]
        if shape(feature["geometry"]).contains(Point(lon, lat)):
            correct += 1
    if checked == 0:
        pytest.skip("aucune méta regional avec coordonnées")
    print(f"\nTaux de justesse mesuré: {correct}/{checked} = {correct / checked:.0%}")
    assert correct / checked >= 0.7, f"sous la cible de 70 % : {correct}/{checked}"
```

- [ ] **Step 3: Lancer les tests, vérifier qu'ils échouent ou sautent**

Run: `uv run pytest tests/test_real_data.py -v`
Expected: SKIPPED — `data/geo/PL.geojson` n'existe pas encore.

- [ ] **Step 4: Écrire `cartometa/geo/cli.py`**

```python
from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from shapely.geometry import Point, mapping, shape
from skimage.measure import label, regionprops

from cartometa.config import Config, load_config
from cartometa.geo.calibrate import Calibration, fit_calibration, load_calibration, save_calibration
from cartometa.geo.confidence import evaluate
from cartometa.geo.reference import country_geometry
from cartometa.geo.silhouette import find_inset
from cartometa.geo.vectorize import buffer_km, mask_to_geometry, zone_mask


def _load_rgba(path: str) -> np.ndarray:
    return np.array(Image.open(path).convert("RGBA"))


def _existing_statuses(path: Path) -> dict[str, dict]:
    """Préserve les décisions de revue déjà prises."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text("utf-8"))
    return {
        f["properties"]["id"]: f
        for f in data.get("features", [])
        if f["properties"].get("status") in ("validé", "corrigé", "rejeté")
    }


def _calibration_for(country: str, metas: list[dict], data_dir: Path, cfg: Config) -> Calibration | None:
    """Calibre une fois par pays, à partir d'une méta dont la silhouette est intacte."""
    path = data_dir / "calib" / f"{country}.json"
    if path.exists():
        return load_calibration(path)

    reference = country_geometry(country, data_dir / "cache")
    # Une méta `spot` est préférée : son pin n'ampute pas la silhouette.
    ordered = sorted(metas, key=lambda m: 0 if m["tier"] == "spot" else 1)
    for meta in ordered:
        if not meta.get("image"):
            continue
        inset = find_inset(_load_rgba(meta["image"]), cfg)
        if inset is None:
            continue
        calib = fit_calibration(inset.mask, reference, cfg)
        save_calibration(path, calib)
        return calib
    return None


def build_country(country: str, data_dir: Path, cfg: Config) -> dict:
    metas = json.loads((data_dir / "metas" / f"{country}.json").read_text("utf-8"))
    reference = country_geometry(country, data_dir / "cache")
    out_path = data_dir / "geo" / f"{country}.geojson"
    preserved = _existing_statuses(out_path)

    calib = _calibration_for(country, metas, data_dir, cfg)
    radii = cfg.get("spot.radius_by_category", {})
    features, stats = [], {"country": 0, "spot": 0, "regional": 0, "failed": 0}

    for meta in metas:
        if meta["id"] in preserved:
            features.append(preserved[meta["id"]])
            continue

        geometry, warnings, component_count = None, [], 0
        touches_border, area_fraction, iou = False, None, calib.iou if calib else None

        if meta["tier"] == "country":
            geometry = reference
            stats["country"] += 1

        elif meta["tier"] == "spot":
            if meta.get("maps_latlon"):
                lat, lon = meta["maps_latlon"]
                radius = radii.get(meta["category"], cfg.get("spot.default_radius_km"))
                geometry = buffer_km(Point(lon, lat), radius)
                stats["spot"] += 1
            else:
                warnings.append("méta ponctuelle sans lien Maps, position inconnue")

        elif meta["tier"] == "regional":
            if not meta.get("image"):
                warnings.append("image absente")
            elif calib is None:
                warnings.append("aucune calibration disponible pour ce pays")
            else:
                rgba = _load_rgba(meta["image"])
                inset = find_inset(rgba, cfg)
                if inset is None:
                    warnings.append("aucun encart cartographique détecté")
                else:
                    mask = zone_mask(rgba, inset, cfg)
                    component_count = sum(
                        1 for r in regionprops(label(mask))
                        if r.area >= cfg.get("vectorize.min_component_px")
                    )
                    x0, y0, x1, y1 = inset.bbox
                    edge = mask[y0:y1, x0:x1]
                    if edge.size:
                        touches_border = bool(
                            edge[0].any() or edge[-1].any() or edge[:, 0].any() or edge[:, -1].any()
                        )
                    geometry = mask_to_geometry(mask, calib, cfg)
                    if geometry is not None and reference.area > 0:
                        area_fraction = geometry.intersection(reference).area / reference.area
                    stats["regional"] += 1

        score, auto_warnings = evaluate(
            geometry, tier=meta["tier"], calib_iou=iou, latlon=meta.get("maps_latlon"),
            component_count=component_count, touches_border=touches_border,
            area_fraction_of_country=area_fraction, cfg=cfg,
        )
        warnings = warnings + auto_warnings
        if geometry is None:
            stats["failed"] += 1

        features.append({
            "type": "Feature",
            "geometry": mapping(geometry) if geometry is not None else None,
            "properties": {
                "id": meta["id"], "confidence": round(score, 3),
                "warnings": warnings, "status": "auto",
            },
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2, ensure_ascii=False),
        "utf-8",
    )
    stats["total"] = len(features)
    stats["output"] = str(out_path)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Construit les géométries des métas")
    parser.add_argument("country", nargs="?", default="PL")
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args()
    stats = build_country(args.country, args.data, load_config())
    print(f"{args.country}: {stats['total']} métas — "
          f"national {stats['country']}, ponctuel {stats['spot']}, régional {stats['regional']}, "
          f"échecs {stats['failed']}")
    print(f"  écrit: {stats['output']}")
```

- [ ] **Step 5: Lancer le pipeline complet sur la Pologne**

Run: `uv run cartometa-geo PL`
Expected: `data/geo/PL.geojson` écrit, avec les trois tiers renseignés et un nombre d'échecs faible.

- [ ] **Step 6: Lancer les tests sur données réelles et relever le taux**

Run: `uv run pytest tests/test_real_data.py -v -s -m real_data`
Expected: les trois premiers tests passent. Le quatrième affiche le **taux de justesse mesuré** — c'est le chiffre qui décide de la suite du projet.

**Si le taux est sous 70 % :** ne pas ajuster les seuils jusqu'à ce que le test passe. Relever la valeur, l'inscrire au rapport de Task 12, et diagnostiquer méta par méta dans l'interface de revue de Task 11 avant toute correction.

- [ ] **Step 7: Vérifier la préservation des statuts de revue**

```bash
uv run python -c "
import json; from pathlib import Path
p = Path('data/geo/PL.geojson'); d = json.loads(p.read_text('utf-8'))
d['features'][0]['properties']['status'] = 'validé'
p.write_text(json.dumps(d, indent=2, ensure_ascii=False), 'utf-8')
print('marqué validé:', d['features'][0]['properties']['id'])
"
uv run cartometa-geo PL
uv run python -c "
import json; from pathlib import Path
d = json.loads(Path('data/geo/PL.geojson').read_text('utf-8'))
print('statut après reconstruction:', d['features'][0]['properties']['status'])
"
```

Expected: le statut reste `validé`. Une reconstruction ne doit jamais effacer le travail de revue.

- [ ] **Step 8: Commit**

```bash
git add cartometa/geo/cli.py tests/test_real_data.py pyproject.toml data/calib
git commit -m "feat: commande build-geo avec aiguillage par tier"
```

---

### Task 11: Interface de revue au clavier

**Files:**
- Create: `cartometa/review/__init__.py`, `cartometa/review/server.py`
- Create: `cartometa/review/static/index.html`, `cartometa/review/static/app.js`

**Interfaces:**
- Consumes: `data/metas/<CC>.json`, `data/geo/<CC>.geojson`
- Produces: serveur local sur `http://127.0.0.1:8765`. API : `GET /api/queue` retourne la file triée par confiance croissante ; `POST /api/decision` avec `{"id": str, "status": str, "radius_km": float | null}` persiste par écriture atomique.

Objectif : **moins de 10 secondes par méta**. Le point Maps est affiché sur la carte — s'il tombe hors du polygone, le rejet est immédiat.

- [ ] **Step 1: Écrire `cartometa/review/server.py`**

```python
from __future__ import annotations
import argparse
import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from shapely.geometry import Point, mapping, shape

STATIC = Path(__file__).resolve().parent / "static"
STATE = {"data": Path("data"), "country": "PL"}


def _paths() -> tuple[Path, Path]:
    data, country = STATE["data"], STATE["country"]
    return data / "metas" / f"{country}.json", data / "geo" / f"{country}.geojson"


def _write_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), "utf-8")
    os.replace(temporary, path)


def build_queue() -> dict:
    metas_path, geo_path = _paths()
    metas = {m["id"]: m for m in json.loads(metas_path.read_text("utf-8"))}
    geo = json.loads(geo_path.read_text("utf-8"))

    items = []
    for feature in geo["features"]:
        props = feature["properties"]
        meta = metas.get(props["id"])
        if meta is None:
            continue
        items.append({
            "id": props["id"],
            "title": meta["title"],
            "description": meta["description"],
            "tier": meta["tier"],
            "category": meta["category"],
            "image": "/" + meta["image"] if meta.get("image") else None,
            "latlon": meta.get("maps_latlon"),
            "source_url": meta["source_url"],
            "confidence": props["confidence"],
            "warnings": props["warnings"],
            "status": props["status"],
            "geometry": feature["geometry"],
        })
    pending = [i for i in items if i["status"] == "auto"]
    pending.sort(key=lambda i: i["confidence"])
    return {"total": len(items), "reviewed": len(items) - len(pending), "items": pending}


def apply_decision(meta_id: str, status: str, radius_km: float | None) -> None:
    _, geo_path = _paths()
    geo = json.loads(geo_path.read_text("utf-8"))
    for feature in geo["features"]:
        if feature["properties"]["id"] != meta_id:
            continue
        feature["properties"]["status"] = status
        if radius_km and feature["geometry"]:
            from cartometa.geo.vectorize import buffer_km

            centre = shape(feature["geometry"]).centroid
            feature["geometry"] = mapping(buffer_km(Point(centre.x, centre.y), radius_km))
            feature["properties"]["status"] = "corrigé"
        break
    _write_atomic(geo_path, geo)


class Handler(SimpleHTTPRequestHandler):
    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/api/queue":
            self._json(build_queue())
            return
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            self.directory = str(STATIC)
        elif self.path.startswith("/app.js"):
            self.directory = str(STATIC)
        super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/api/decision":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        apply_decision(payload["id"], payload["status"], payload.get("radius_km"))
        self._json({"ok": True})

    def log_message(self, *args) -> None:
        pass  # silence : le compteur de progression est dans l'interface


def main() -> None:
    parser = argparse.ArgumentParser(description="Interface de revue des géométries")
    parser.add_argument("country", nargs="?", default="PL")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    STATE["data"], STATE["country"] = args.data, args.country

    # Les images sont servies depuis la racine du projet (chemins relatifs des métas).
    os.chdir(Path.cwd())
    print(f"Revue {args.country} : http://127.0.0.1:{args.port}")
    print("Touches — A valider, R rejeter, Espace passer, U annuler")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
```

- [ ] **Step 2: Écrire `cartometa/review/static/index.html`**

```html
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Cartometa — revue</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    body { margin: 0; font: 14px system-ui, sans-serif; }
    header { display: flex; gap: 16px; align-items: center; padding: 8px 12px;
             background: #1c1f24; color: #fff; }
    header b { font-size: 16px; }
    #panes { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 8px; }
    #source img { width: 100%; border: 1px solid #ccc; }
    #map { height: 62vh; border: 1px solid #ccc; }
    #info { padding: 8px 12px; }
    #warnings { color: #b00020; }
    kbd { background: #eee; border-radius: 3px; padding: 1px 5px; border: 1px solid #bbb; }
  </style>
</head>
<body>
  <header>
    <b id="progress">…</b>
    <span id="confidence"></span>
    <span style="margin-left:auto">
      <kbd>A</kbd> valider <kbd>R</kbd> rejeter <kbd>Espace</kbd> passer <kbd>U</kbd> annuler
    </span>
  </header>
  <div id="panes">
    <div id="source"><img id="image" alt=""></div>
    <div id="map"></div>
  </div>
  <div id="info">
    <h2 id="title"></h2>
    <p id="description"></p>
    <p id="warnings"></p>
    <p id="radius-row" hidden>
      Rayon <input id="radius" type="range" min="5" max="120" step="5">
      <span id="radius-value"></span> km — <kbd>Entrée</kbd> pour appliquer
    </p>
    <a id="source-link" target="_blank" rel="noopener">source</a>
  </div>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Écrire `cartometa/review/static/app.js`**

```javascript
const map = L.map('map').setView([52, 19], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 18,
}).addTo(map);

let queue = [];
let index = 0;
let total = 0;
let reviewed = 0;
let history = [];
let layers = L.layerGroup().addTo(map);

async function loadQueue() {
  const response = await fetch('/api/queue');
  const data = await response.json();
  queue = data.items;
  total = data.total;
  reviewed = data.reviewed;
  index = 0;
  render();
}

function current() {
  return queue[index];
}

function render() {
  const item = current();
  if (!item) {
    document.getElementById('progress').textContent = `Terminé — ${total} métas revues`;
    document.getElementById('title').textContent = '';
    layers.clearLayers();
    return;
  }
  document.getElementById('progress').textContent =
    `${reviewed + index} / ${total}`;
  document.getElementById('confidence').textContent =
    `confiance ${item.confidence.toFixed(2)} — ${item.tier}`;
  document.getElementById('image').src = item.image || '';
  document.getElementById('title').textContent = item.title;
  document.getElementById('description').textContent = item.description;
  document.getElementById('warnings').textContent = item.warnings.join(' · ');
  document.getElementById('source-link').href = item.source_url;

  const isSpot = item.tier === 'spot';
  document.getElementById('radius-row').hidden = !isSpot;

  layers.clearLayers();
  if (item.geometry) {
    const shape = L.geoJSON(item.geometry, { color: '#c1283a', weight: 2 }).addTo(layers);
    map.fitBounds(shape.getBounds(), { padding: [30, 30], maxZoom: 9 });
  }
  if (item.latlon) {
    // Vérité terrain : hors du polygone, le rejet est immédiat.
    L.circleMarker([item.latlon[0], item.latlon[1]], {
      radius: 6, color: '#0057d9', fillOpacity: 0.9,
    }).addTo(layers);
  }
}

async function decide(status, radiusKm) {
  const item = current();
  if (!item) return;
  history.push(item.id);
  await fetch('/api/decision', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: item.id, status, radius_km: radiusKm ?? null }),
  });
  index += 1;
  render();
}

document.addEventListener('keydown', (event) => {
  if (event.target.tagName === 'INPUT' && event.key !== 'Enter') return;
  switch (event.key.toLowerCase()) {
    case 'a': decide('validé'); break;
    case 'r': decide('rejeté'); break;
    case ' ': event.preventDefault(); index += 1; render(); break;
    case 'u':
      if (history.length) {
        history.pop();
        index = Math.max(0, index - 1);
        render();
      }
      break;
    case 'enter':
      if (current() && current().tier === 'spot') {
        decide('corrigé', Number(document.getElementById('radius').value));
      }
      break;
  }
});

const radius = document.getElementById('radius');
radius.addEventListener('input', () => {
  document.getElementById('radius-value').textContent = radius.value;
});

loadQueue();
```

- [ ] **Step 4: Lancer l'interface et revoir la Pologne entière**

Run: `uv run cartometa-review PL` puis ouvrir `http://127.0.0.1:8765`

Expected: la file s'ouvre sur la méta la moins sûre. Revoir les 38 métas au clavier.

**Relever deux chiffres**, ils conditionnent la suite du projet :
- le **temps moyen par méta** — la cible est sous 10 secondes ;
- le **nombre de métas validées sans retouche**, rapporté au total.

- [ ] **Step 5: Vérifier la persistance et la reprise**

Interrompre le serveur au milieu de la revue, le relancer, recharger la page.
Expected: les métas déjà décidées ne réapparaissent pas, le compteur reprend au bon endroit.

- [ ] **Step 6: Commit**

```bash
git add cartometa/review
git commit -m "feat: interface de revue au clavier avec vérité terrain Maps"
```

---

### Task 12: Viewer public statique et rapport

**Files:**
- Create: `viewer/index.html`, `viewer/app.js`, `viewer/style.css`
- Create: `cartometa/geo/export.py`
- Create: `docs/rapport-pologne.md`
- Modify: `pyproject.toml` (script `cartometa-export`)

**Interfaces:**
- Consumes: `data/metas/<CC>.json`, `data/geo/<CC>.geojson`
- Produces: `export_viewer(data_dir: Path, out_dir: Path, countries: list[str]) -> dict` écrivant `viewer/data/index.json` (léger : textes et bounding boxes) et `viewer/data/geometries.json` (lourd). Seules les métas de statut `validé` ou `corrigé` sont exportées.

Le filtre bbox suivi du test point-dans-polygone tient sous la milliseconde à cette échelle : aucune librairie d'index spatial n'est justifiée.

- [ ] **Step 1: Écrire `cartometa/geo/export.py`**

```python
from __future__ import annotations
import argparse
import json
from pathlib import Path

from shapely.geometry import shape

EXPORTABLE = ("validé", "corrigé")


def export_viewer(data_dir: Path, out_dir: Path, countries: list[str]) -> dict:
    index, geometries = [], {}
    for country in countries:
        metas = {m["id"]: m for m in json.loads((data_dir / "metas" / f"{country}.json").read_text("utf-8"))}
        geo = json.loads((data_dir / "geo" / f"{country}.geojson").read_text("utf-8"))
        for feature in geo["features"]:
            props = feature["properties"]
            if props["status"] not in EXPORTABLE or not feature["geometry"]:
                continue
            meta = metas.get(props["id"])
            if meta is None:
                continue
            geom = shape(feature["geometry"])
            index.append({
                "id": props["id"], "country": country, "tier": meta["tier"],
                "title": meta["title"], "description": meta["description"],
                "category": meta["category"], "image": meta.get("image"),
                "source_url": meta["source_url"],
                "bbox": [round(v, 4) for v in geom.bounds],
                "area": round(geom.area, 6),
            })
            geometries[props["id"]] = feature["geometry"]

    index.sort(key=lambda entry: entry["area"])
    target = out_dir / "data"
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.json").write_text(json.dumps(index, ensure_ascii=False), "utf-8")
    (target / "geometries.json").write_text(json.dumps(geometries, ensure_ascii=False), "utf-8")
    return {"exported": len(index), "countries": countries, "output": str(target)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporte les données du viewer")
    parser.add_argument("countries", nargs="*", default=["PL"])
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("viewer"))
    args = parser.parse_args()
    result = export_viewer(args.data, args.out, args.countries)
    print(f"{result['exported']} métas exportées vers {result['output']}")
```

Ajouter dans `pyproject.toml` :

```toml
cartometa-export = "cartometa.geo.export:main"
```

- [ ] **Step 2: Écrire `viewer/index.html`**

```html
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cartometa</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div id="map"></div>
  <aside id="panel">
    <header>
      <input id="search" type="search" placeholder="Rechercher…">
      <select id="category">
        <option value="">Toutes catégories</option>
        <option value="bollards">Bollards</option>
        <option value="poteaux">Poteaux</option>
        <option value="vehicule">Véhicule</option>
        <option value="vegetation">Végétation</option>
        <option value="signalisation">Signalisation</option>
        <option value="autre">Autre</option>
      </select>
    </header>
    <p id="hint">Cliquez sur la carte pour voir les métas applicables.</p>
    <ul id="results"></ul>
  </aside>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Écrire `viewer/style.css`**

```css
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 system-ui, sans-serif; }
#map { position: absolute; inset: 0 380px 0 0; }
#panel { position: absolute; top: 0; right: 0; bottom: 0; width: 380px;
         overflow-y: auto; background: #fff; border-left: 1px solid #ddd; padding: 12px; }
#panel header { display: flex; gap: 8px; margin-bottom: 12px; }
#panel input, #panel select { flex: 1; min-width: 0; padding: 6px; }
#results { list-style: none; margin: 0; padding: 0; }
#results li { border-bottom: 1px solid #eee; padding: 10px 4px; cursor: pointer; }
#results li:hover { background: #f4f7ff; }
#results img { width: 100%; border-radius: 4px; margin-top: 6px; }
.badge { font-size: 12px; background: #eef; border-radius: 3px; padding: 1px 6px; }

@media (max-width: 760px) {
  #map { inset: 0 0 45vh 0; }
  #panel { top: auto; height: 45vh; width: 100%; border-left: none; border-top: 1px solid #ddd; }
}
```

- [ ] **Step 4: Écrire `viewer/app.js`**

```javascript
const map = L.map('map').setView([52, 19], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 18,
}).addTo(map);

let index = [];
let geometries = {};
let matches = [];
const highlight = L.layerGroup().addTo(map);

Promise.all([
  fetch('data/index.json').then((r) => r.json()),
  fetch('data/geometries.json').then((r) => r.json()),
]).then(([loadedIndex, loadedGeometries]) => {
  index = loadedIndex;
  geometries = loadedGeometries;
});

function insideRing(lon, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function insidePolygon(lon, lat, rings) {
  if (!insideRing(lon, lat, rings[0])) return false;
  for (let i = 1; i < rings.length; i += 1) {
    if (insideRing(lon, lat, rings[i])) return false; // trou
  }
  return true;
}

function contains(geometry, lon, lat) {
  if (geometry.type === 'Polygon') return insidePolygon(lon, lat, geometry.coordinates);
  return geometry.coordinates.some((rings) => insidePolygon(lon, lat, rings));
}

function query(lon, lat) {
  // Filtre bbox d'abord : élimine la quasi-totalité des candidats en une passe.
  return index.filter((entry) => {
    const [minLon, minLat, maxLon, maxLat] = entry.bbox;
    if (lon < minLon || lon > maxLon || lat < minLat || lat > maxLat) return false;
    return contains(geometries[entry.id], lon, lat);
  });
}

function visible() {
  const term = document.getElementById('search').value.trim().toLowerCase();
  const category = document.getElementById('category').value;
  return matches.filter((entry) => {
    if (category && entry.category !== category) return false;
    if (!term) return true;
    return (entry.title + ' ' + entry.description).toLowerCase().includes(term);
  });
}

function render() {
  const list = document.getElementById('results');
  const entries = visible();
  document.getElementById('hint').textContent = entries.length
    ? `${entries.length} méta(s) — de la plus spécifique à la plus générale`
    : 'Aucune méta pour ce point.';
  list.innerHTML = '';
  for (const entry of entries) {
    const item = document.createElement('li');
    item.innerHTML =
      `<span class="badge">${entry.category}</span> <strong>${entry.title}</strong>` +
      `<div>${entry.description}</div>` +
      (entry.image ? `<img loading="lazy" src="../${entry.image}" alt="">` : '') +
      `<a href="${entry.source_url}" target="_blank" rel="noopener">source</a>`;
    item.addEventListener('mouseenter', () => {
      highlight.clearLayers();
      L.geoJSON(geometries[entry.id], { color: '#c1283a', weight: 2 }).addTo(highlight);
    });
    list.appendChild(item);
  }
}

map.on('click', (event) => {
  const started = performance.now();
  // index est déjà trié par surface croissante : du plus spécifique au plus général.
  matches = query(event.latlng.lng, event.latlng.lat);
  console.debug(`requête en ${(performance.now() - started).toFixed(1)} ms`);
  highlight.clearLayers();
  render();
});

document.getElementById('search').addEventListener('input', render);
document.getElementById('category').addEventListener('change', render);
```

- [ ] **Step 5: Exporter et vérifier le viewer**

```bash
uv run cartometa-export PL
uv run python -m http.server 8080
```

Ouvrir `http://127.0.0.1:8080/viewer/`.

Expected, à vérifier explicitement :
- un clic sur Varsovie retourne les métas nationales ;
- un clic sur les Tatras retourne en plus la méta ponctuelle, **classée avant** les nationales ;
- un clic en plein Atlantique affiche « Aucune méta pour ce point. », sans erreur en console ;
- la durée affichée en console reste **sous 100 ms** ;
- en fenêtre étroite, le panneau passe sous la carte et reste utilisable.

- [ ] **Step 6: Écrire `docs/rapport-pologne.md`**

Rapport court, rempli avec les chiffres réellement mesurés — jamais estimés.

```markdown
# Rapport — verticale Pologne

## Chiffres mesurés

- Métas extraites : … (national …, régional …, ponctuel …)
- Métas sans image : …   sans lien Maps : …
- IoU de calibration PL : …
- Taux de justesse automatique (point Maps dans le polygone) : … / … = … %
- Métas validées sans retouche à la revue : … / … = … %
- Temps moyen de revue par méta : … s
- Latence de requête du viewer : … ms

## Ce qui fonctionne

…

## Limites connues

…

## Décision sur l'éditeur de sommets

Le taux de validation sans retouche mesuré est de … %. La spec (§6.1) reporte la
construction de l'éditeur de sommets jusqu'à ce chiffre.

Décision : …

## Pays problématiques et prochaine étape

…
```

- [ ] **Step 7: Lancer la suite de tests complète**

Run: `uv run pytest -v`
Expected: tous les tests passent, y compris `real_data`.

- [ ] **Step 8: Commit**

```bash
git add viewer cartometa/geo/export.py docs/rapport-pologne.md pyproject.toml
git commit -m "feat: viewer statique et rapport de la verticale Pologne"
```

---

## Auto-relecture

**Couverture de la spec.** §2 acquisition manuelle → Task 4 lit `input/`, aucun crawler nulle part. §4 extracteur et tous ses champs → Tasks 2, 3, 4. §5 stages 0 à 3 → Tasks 6, 7, 8 ; aiguillage par tier → Task 10 ; cas dégénérés et confiance → Task 9 ; vérification par point Maps → Tasks 9 et 10. §6.1 revue clavier et persistance → Task 11 ; report de l'éditeur de sommets → assumé, tracé au rapport de Task 12. §6.2 viewer statique, tri par surface, filtres, responsive → Task 12. §7 critères d'acceptation → `tests/test_real_data.py` en Task 10, plus les vérifications manuelles de Task 12 Step 5. §8 verticale Pologne → l'ordre des tâches est cette verticale.

**Écarts assumés.** La calibration est ajustée sur une méta `spot` plutôt que sur n'importe laquelle : son pin n'ampute pas la silhouette, contrairement à une zone régionale étendue. Le recadrage rectangulaire de l'encart prévu au Stage 0 est remplacé par un masquage à l'intérieur de la silhouette — strictement plus robuste, et validé par la mesure du rouge parasite atteignant x=0 sur `Poland-southern-hills`.

**Cohérence des types.** `Config.get` en notation pointée est utilisé partout de façon identique. `Inset.mask` est pleine taille image dans `silhouette.py`, `vectorize.py` et `cli.py`. `Calibration.pixel_to_lonlat` retourne `(lon, lat)` — ordre GeoJSON — tandis que `maps_latlon` reste `(lat, lon)`, ordre Google ; les deux conversions passent par `Point(lon, lat)` dans `confidence.py`, `cli.py` et `app.js`. `buffer_km` est défini dans `vectorize.py` et consommé par `cli.py` et `review/server.py`. Les quatre statuts `auto`, `validé`, `corrigé`, `rejeté` sont employés de façon identique en Tasks 10, 11 et 12.
