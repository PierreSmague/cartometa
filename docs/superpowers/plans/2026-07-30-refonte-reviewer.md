# Refonte du reviewer — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supprimer toute la détection automatique de polygones et refondre le reviewer pour que chaque emprise soit tracée à la main, par cumul de morceaux (rectangle, contour libre, régions admin-1, pays entier), avec saisie de métas manuelles.

**Architecture:** Le client n'envoie jamais de polygone Natural Earth : il envoie une liste de *descripteurs de morceaux*, que le serveur résout, unit avec shapely, valide et écrit. Les métas viennent de deux sources fusionnées à la lecture — l'import Plonk It (gitignoré, régénérable) et la saisie manuelle (versionnée, irremplaçable). Le front est découpé en cinq modules ES servis sans build.

**Tech Stack:** Python 3.14, shapely, Pillow, selectolax, pytest, `uv`. Front : Leaflet 1.9.4 depuis unpkg, modules ES natifs, aucun bundler.

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-07-30-refonte-reviewer-design.md`. En cas de contradiction avec ce plan, la spec fait foi.
- Langue : tout le code, les commentaires, les docstrings, les messages d'erreur et les messages de commit sont en français, comme le reste du dépôt. Les messages de commit évitent les accents (contrainte de l'historique existant).
- Statuts : exactement deux, `"validé"` et `"rejeté"`. Aucun `auto`, aucun `corrigé`.
- Identifiants des métas manuelles : `man-` suivi de 4 caractères hexadécimaux.
- Toute écriture d'un fichier de données passe par `cartometa.atomic_write.write_json_atomic`.
- Aucun test ne touche le réseau. Les datasets Natural Earth sont injectés via un `downloader` ou pré-écrits dans le cache, comme le fait déjà `tests/test_reference.py`.
- Le serveur de revue n'écoute que sur `127.0.0.1`.
- Un nom de fichier écrit sur disque ne provient jamais du client.
- `data/manual/` doit rester versionné : ne jamais l'ajouter au `.gitignore`.
- Commande de test : `uv run pytest`. Elle doit être verte à la fin de chaque tâche.

---

## Structure des fichiers

**Supprimés**

| Fichier | Responsabilité disparue |
|---|---|
| `cartometa/geo/calibrate.py` | calibration pixel → WGS84 |
| `cartometa/geo/silhouette.py` | détection de l'encart cartographique |
| `cartometa/geo/vectorize.py` | vectorisation de la zone rouge |
| `cartometa/geo/confidence.py` | score de confiance |
| `cartometa/geo/cli.py` | pipeline `cartometa-geo` |
| `cartometa/config.py` | plus aucun consommateur après suppression des seuils |
| `config/defaults.toml` | idem |
| `tests/fixtures.py` | générateur d'images de test du template Plonk It |
| `tests/test_calibrate.py`, `test_silhouette.py`, `test_vectorize.py`, `test_confidence.py`, `test_geo_cli.py`, `test_review_offset.py`, `test_config.py` | tests des modules supprimés |

**Créés**

| Fichier | Responsabilité |
|---|---|
| `cartometa/geo/admin1.py` | dataset Natural Earth admin-1 : extraction par pays, résolution d'un code de région |
| `cartometa/review/pieces.py` | résolution d'une liste de morceaux en une géométrie unique |
| `cartometa/review/store.py` | chemins d'un pays, fusion des deux sources de métas, lecture/écriture des décisions |
| `cartometa/review/manual.py` | création d'une méta manuelle, écriture de son image |
| `cartometa/review/static/api.js` | appels HTTP et remontée d'erreurs |
| `cartometa/review/static/geometry.js` | construction de géométries et test point-dans-polygone |
| `cartometa/review/static/sketch.js` | état des morceaux, modes de tracé, rendu Leaflet |
| `cartometa/review/static/manual.js` | formulaire de méta manuelle |
| `tests/test_admin1.py`, `test_pieces.py`, `test_store.py`, `test_manual_meta.py` | tests des modules créés |

**Modifiés**

| Fichier | Changement |
|---|---|
| `cartometa/models.py` | `GeoRecord` refondu, `MetaRecord.origin`, constantes de statut |
| `cartometa/geo/reference.py` | téléchargeur générique `ensure_file`, partagé avec admin-1 |
| `cartometa/geo/export.py` | statut unique, double source de métas |
| `cartometa/review/server.py` | réécrit autour des nouveaux modules |
| `cartometa/review/static/index.html`, `app.js` | réécrits |
| `cartometa/atomic_write.py` | docstring : ne plus citer `geo/cli.py` |
| `pyproject.toml` | entry points, dépendances |
| `README.md`, `docs/rapport-pologne.md` | documentation |
| `tests/test_export.py`, `tests/test_real_data.py` | adaptés |

---

### Task 1 : Élaguer la détection automatique

Aucune fonctionnalité ajoutée. On retire le code mort avant de construire dessus, pour que les tâches suivantes travaillent sur un dépôt propre. `cartometa-review` continue de fonctionner sur l'ancien format jusqu'à la Task 6.

**Files:**
- Delete: `cartometa/geo/calibrate.py`, `cartometa/geo/silhouette.py`, `cartometa/geo/vectorize.py`, `cartometa/geo/confidence.py`, `cartometa/geo/cli.py`, `cartometa/config.py`, `config/defaults.toml`
- Delete: `tests/fixtures.py`, `tests/test_calibrate.py`, `tests/test_silhouette.py`, `tests/test_vectorize.py`, `tests/test_confidence.py`, `tests/test_geo_cli.py`, `tests/test_review_offset.py`, `tests/test_config.py`
- Modify: `pyproject.toml`, `cartometa/atomic_write.py:17-21`

**Interfaces:**
- Consumes: rien
- Produces: un dépôt où `cartometa/geo/` ne contient plus que `reference.py` et `export.py`, et où `numpy`, `scipy`, `scikit-image` ne sont plus des dépendances

- [ ] **Step 1 : Supprimer les modules de détection et leurs tests**

```bash
git rm cartometa/geo/calibrate.py cartometa/geo/silhouette.py \
       cartometa/geo/vectorize.py cartometa/geo/confidence.py cartometa/geo/cli.py \
       cartometa/config.py config/defaults.toml
git rm tests/fixtures.py tests/test_calibrate.py tests/test_silhouette.py \
       tests/test_vectorize.py tests/test_confidence.py tests/test_geo_cli.py \
       tests/test_review_offset.py tests/test_config.py
```

- [ ] **Step 2 : Retirer l'entry point et les dépendances devenues inutiles**

Dans `pyproject.toml`, supprimer la ligne `cartometa-geo = "cartometa.geo.cli:main"` de `[project.scripts]`, et retirer `numpy`, `scikit-image`, `scipy` de `dependencies`. Le bloc devient :

```toml
dependencies = [
    "pillow>=12.3.0",
    "selectolax>=0.4.11",
    "shapely>=2.1.2",
]
```

```toml
[project.scripts]
cartometa-extract = "cartometa.extract.cli:main"
cartometa-review = "cartometa.review.server:main"
cartometa-export = "cartometa.geo.export:main"
```

`pillow` reste : la Task 5 s'en sert pour valider les images déposées.

- [ ] **Step 3 : Vérifier qu'aucun import orphelin ne subsiste**

Run: `uv run python -c "import cartometa.extract.cli, cartometa.geo.export, cartometa.geo.reference, cartometa.review.server"`
Expected: aucune sortie, aucune erreur.

Run: `grep -rn "numpy\|skimage\|scipy\|cartometa.config\|geo.cli\|geo import cli" --include=*.py cartometa tests`
Expected: aucun résultat.

- [ ] **Step 4 : Corriger la docstring de `atomic_write`**

Remplacer, dans `cartometa/atomic_write.py`, le paragraphe qui cite `cartometa/geo/cli.py` :

```python
    Utilisé par le serveur de revue (`cartometa/review/server.py`), qui porte
    le seul travail humain irremplaçable du dépôt : les géométries tracées à
    la main.
```

- [ ] **Step 5 : Lancer la suite complète**

Run: `uv sync && uv run pytest`
Expected: PASS, sans erreur de collecte. Les tests restants sont ceux de `extract`, `reference`, `export`, `maps_links`, `categories`, `html_parser`, `atomic_write`, `real_data`.

- [ ] **Step 6 : Commit**

```bash
git add -A
git commit -m "refactor: supprimer la detection automatique de polygones

Calibration, silhouette, vectorisation et score de confiance disparaissent
avec la commande cartometa-geo : les emprises seront desormais tracees a la
main. numpy, scipy et scikit-image ne sont plus necessaires."
```

---

### Task 2 : Régions administratives de niveau 1

**Files:**
- Create: `cartometa/geo/admin1.py`
- Modify: `cartometa/geo/reference.py:27-42`
- Test: `tests/test_admin1.py`

**Interfaces:**
- Consumes: `cartometa.geo.reference.ensure_dataset` (comportement inchangé), `cartometa.atomic_write.write_json_atomic`
- Produces:
  - `reference.ensure_file(url: str, name: str, cache_dir: Path, downloader: Downloader = _urlretrieve) -> Path`
  - `admin1.ADMIN1_URL: str`, `admin1.ADMIN1_NAME: str`
  - `admin1.country_regions(iso_a2: str, cache_dir: Path, downloader: Downloader = _urlretrieve) -> dict` — FeatureCollection dont chaque feature porte `properties = {"code": str, "name": str}`
  - `admin1.region_geometry(iso_a2: str, code: str, cache_dir: Path) -> BaseGeometry` — lève `KeyError` si le code est inconnu

- [ ] **Step 1 : Écrire les tests**

Créer `tests/test_admin1.py` :

```python
import json
from pathlib import Path

import pytest

from cartometa.geo.admin1 import ADMIN1_NAME, country_regions, region_geometry


def _box(x0, y0, x1, y1):
    return {"type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


FAKE = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"adm1_code": "POL-1", "iso_a2": "PL", "name": "Mazowieckie"},
     "geometry": _box(20.0, 51.0, 22.0, 53.0)},
    {"type": "Feature",
     "properties": {"adm1_code": "POL-2", "iso_a2": "pl", "name": None,
                    "name_en": "Malopolskie"},
     "geometry": _box(19.0, 49.0, 21.0, 50.5)},
    {"type": "Feature",
     "properties": {"adm1_code": "FRA-1", "iso_a2": "FR", "name": "Bretagne"},
     "geometry": _box(-5.0, 47.0, -1.0, 49.0)},
]}


@pytest.fixture
def cache_dir(tmp_path):
    (tmp_path / ADMIN1_NAME).write_text(json.dumps(FAKE), "utf-8")
    return tmp_path


def test_seules_les_regions_du_pays_sont_extraites(cache_dir):
    regions = country_regions("PL", cache_dir)

    codes = {f["properties"]["code"] for f in regions["features"]}
    assert codes == {"POL-1", "POL-2"}


def test_le_code_pays_est_compare_sans_tenir_compte_de_la_casse(cache_dir):
    """Natural Earth n'est pas homogene sur la casse de iso_a2."""
    regions = country_regions("pl", cache_dir)

    assert len(regions["features"]) == 2


def test_le_nom_retombe_sur_name_en_quand_name_est_vide(cache_dir):
    regions = country_regions("PL", cache_dir)

    noms = {f["properties"]["code"]: f["properties"]["name"] for f in regions["features"]}
    assert noms["POL-2"] == "Malopolskie"


def test_l_extraction_est_mise_en_cache_par_pays(cache_dir):
    country_regions("PL", cache_dir)

    assert (cache_dir / "admin1" / "PL.geojson").exists()


def test_le_gros_fichier_n_est_plus_relu_apres_extraction(cache_dir):
    country_regions("PL", cache_dir)
    (cache_dir / ADMIN1_NAME).unlink()

    # Le cache par pays doit suffire : c'est tout l'interet de l'extraction.
    assert len(country_regions("PL", cache_dir)["features"]) == 2


def test_pays_sans_region_leve_keyerror_sans_ecrire_de_cache(cache_dir):
    with pytest.raises(KeyError):
        country_regions("ZZ", cache_dir)

    # Un cache vide empecherait pour toujours une nouvelle tentative.
    assert not (cache_dir / "admin1" / "ZZ.geojson").exists()


def test_le_telechargement_est_injectable(tmp_path):
    appels = []

    def downloader(url: str, dest: Path) -> None:
        appels.append(url)
        dest.write_text(json.dumps(FAKE), "utf-8")

    country_regions("PL", tmp_path, downloader=downloader)

    assert len(appels) == 1


def test_region_geometry_par_code(cache_dir):
    geom = region_geometry("PL", "POL-1", cache_dir)

    assert geom.bounds == (20.0, 51.0, 22.0, 53.0)


def test_region_geometry_code_inconnu(cache_dir):
    with pytest.raises(KeyError):
        region_geometry("PL", "POL-99", cache_dir)
```

- [ ] **Step 2 : Lancer les tests pour les voir échouer**

Run: `uv run pytest tests/test_admin1.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.geo.admin1'`

- [ ] **Step 3 : Extraire le téléchargeur générique dans `reference.py`**

Remplacer le corps de `ensure_dataset` (lignes 27-42) par :

```python
def ensure_file(
    url: str, name: str, cache_dir: Path, downloader: Downloader = _urlretrieve
) -> Path:
    """Télécharge `url` vers `cache_dir / name` s'il n'y est pas déjà.

    Partagé entre le dataset des pays (admin-0) et celui des régions
    (admin-1) : les deux viennent du même dépôt Natural Earth et ont les
    mêmes contraintes de robustesse.
    """
    path = cache_dir / name
    if path.exists():
        return path
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".part")
    try:
        downloader(url, tmp_path)
        os.replace(tmp_path, path)
    finally:
        # Un téléchargement interrompu (réseau, Ctrl-C, disque plein) ne doit
        # jamais laisser de fichier partiel au chemin final, ni de résidu
        # temporaire : sinon les exécutions suivantes échoueraient sur une
        # erreur JSON obscure sans jamais retenter le téléchargement.
        if tmp_path.exists():
            tmp_path.unlink()
    return path


def ensure_dataset(cache_dir: Path, downloader: Downloader = _urlretrieve) -> Path:
    return ensure_file(DATASET_URL, DATASET_NAME, cache_dir, downloader)
```

- [ ] **Step 4 : Écrire `cartometa/geo/admin1.py`**

```python
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from cartometa.atomic_write import write_json_atomic
from cartometa.geo.reference import Downloader, _urlretrieve, ensure_file

ADMIN1_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_admin_1_states_provinces.geojson"
)
ADMIN1_NAME = "ne_10m_admin_1_states_provinces.geojson"


def _country_cache(cache_dir: Path, iso_a2: str) -> Path:
    return cache_dir / "admin1" / f"{iso_a2}.geojson"


@lru_cache(maxsize=8)
def _load(path_str: str) -> dict:
    return json.loads(Path(path_str).read_text("utf-8"))


def _extract(source: dict, iso_a2: str) -> dict:
    """Réduit le dataset mondial aux régions d'un pays, propriétés comprises.

    Le fichier source pèse 41 Mo et porte une centaine de champs par région,
    dont les traductions du nom dans vingt langues. On n'en garde que le code
    et un libellé : c'est ce qui rend le cache par pays assez léger pour être
    envoyé tel quel au navigateur.
    """
    features = []
    for feature in source["features"]:
        props = feature["properties"]
        if (props.get("iso_a2") or "").upper() != iso_a2:
            continue
        name = props.get("name") or props.get("name_en") or props["adm1_code"]
        features.append({
            "type": "Feature",
            "properties": {"code": props["adm1_code"], "name": name},
            "geometry": feature["geometry"],
        })
    return {"type": "FeatureCollection", "features": features}


def country_regions(
    iso_a2: str, cache_dir: Path, downloader: Downloader = _urlretrieve
) -> dict:
    """Régions admin-1 du pays, en FeatureCollection GeoJSON.

    Au premier appel sur un pays, le dataset mondial est téléchargé puis
    réduit dans `cache_dir/admin1/<CC>.geojson`. Les appels suivants ne
    touchent plus au gros fichier — ni même à son existence.
    """
    iso = iso_a2.upper()
    path = _country_cache(cache_dir, iso)
    if not path.exists():
        source_path = ensure_file(ADMIN1_URL, ADMIN1_NAME, cache_dir, downloader)
        extracted = _extract(json.loads(source_path.read_text("utf-8")), iso)
        if not extracted["features"]:
            # Écrire un cache vide condamnerait le pays : plus jamais de
            # nouvelle tentative, et un message d'erreur incompréhensible.
            raise KeyError(f"aucune région admin-1 pour {iso} dans Natural Earth")
        write_json_atomic(path, extracted, indent=None)
    return _load(str(path))


def region_geometry(iso_a2: str, code: str, cache_dir: Path) -> BaseGeometry:
    """Contour d'une région désignée par son `adm1_code` Natural Earth."""
    for feature in country_regions(iso_a2, cache_dir)["features"]:
        if feature["properties"]["code"] == code:
            geom = shape(feature["geometry"])
            return geom if geom.is_valid else geom.buffer(0)
    raise KeyError(f"région admin-1 inconnue pour {iso_a2.upper()} : {code!r}")
```

- [ ] **Step 5 : Lancer les tests**

Run: `uv run pytest tests/test_admin1.py tests/test_reference.py -v`
Expected: PASS pour les deux fichiers. `test_reference.py` valide que le refactor de `ensure_file` n'a rien cassé, notamment `test_failed_download_leaves_no_file_at_final_path`.

- [ ] **Step 6 : Commit**

```bash
git add cartometa/geo/admin1.py cartometa/geo/reference.py tests/test_admin1.py
git commit -m "feat: regions administratives de niveau 1 depuis Natural Earth

Le dataset mondial de 41 Mo est reduit une fois par pays dans un cache
dedie, assez leger pour etre envoye tel quel au navigateur."
```

---

### Task 3 : Résolution des morceaux en géométrie

**Files:**
- Create: `cartometa/review/pieces.py`
- Test: `tests/test_pieces.py`

**Interfaces:**
- Consumes: `admin1.region_geometry`, `reference.country_geometry`
- Produces:
  - `pieces.PieceError` (sous-classe de `ValueError`)
  - `pieces.MIN_RING_POINTS: int = 3`, `pieces.MAX_RING_POINTS: int = 2000`
  - `pieces.resolve_pieces(pieces: list[dict], country: str, cache_dir: Path) -> BaseGeometry`

- [ ] **Step 1 : Écrire les tests**

Créer `tests/test_pieces.py` :

```python
import json

import pytest
from shapely.geometry import shape

from cartometa.geo.admin1 import ADMIN1_NAME
from cartometa.geo.reference import DATASET_NAME
from cartometa.review.pieces import PieceError, resolve_pieces


def _box(x0, y0, x1, y1):
    return {"type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


COUNTRIES = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"ISO_A2": "PL", "ISO_A2_EH": "PL", "NAME": "Poland"},
     "geometry": _box(14.0, 49.0, 24.0, 55.0)},
]}

REGIONS = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"code": "POL-1", "name": "Mazowieckie"},
     "geometry": _box(20.0, 51.0, 22.0, 53.0)},
    {"type": "Feature", "properties": {"code": "POL-2", "name": "Malopolskie"},
     "geometry": _box(19.0, 49.0, 21.0, 50.5)},
]}


@pytest.fixture
def cache_dir(tmp_path):
    (tmp_path / DATASET_NAME).write_text(json.dumps(COUNTRIES), "utf-8")
    (tmp_path / "admin1").mkdir()
    (tmp_path / "admin1" / "PL.geojson").write_text(json.dumps(REGIONS), "utf-8")
    return tmp_path


def test_rectangle(cache_dir):
    geom = resolve_pieces([{"kind": "rect", "bounds": [2.0, 48.0, 3.0, 49.0]}], "PL", cache_dir)

    assert geom.bounds == (2.0, 48.0, 3.0, 49.0)


def test_rectangle_dont_les_coins_sont_donnes_a_l_envers(cache_dir):
    """Deux clics sur la carte peuvent arriver dans n'importe quel ordre."""
    geom = resolve_pieces([{"kind": "rect", "bounds": [3.0, 49.0, 2.0, 48.0]}], "PL", cache_dir)

    assert geom.bounds == (2.0, 48.0, 3.0, 49.0)


def test_pays_entier(cache_dir):
    geom = resolve_pieces([{"kind": "country"}], "PL", cache_dir)

    assert geom.bounds == (14.0, 49.0, 24.0, 55.0)


def test_region_admin1(cache_dir):
    geom = resolve_pieces([{"kind": "admin1", "code": "POL-1"}], "PL", cache_dir)

    assert geom.bounds == (20.0, 51.0, 22.0, 53.0)


def test_contour_libre_est_ferme_automatiquement(cache_dir):
    ring = [[2.0, 48.0], [3.0, 48.0], [3.0, 49.0]]

    geom = resolve_pieces([{"kind": "polygon", "ring": ring}], "PL", cache_dir)

    assert geom.is_valid
    assert geom.area == pytest.approx(0.5)


def test_deux_regions_adjacentes_fusionnent_en_un_polygone(cache_dir):
    geom = resolve_pieces([
        {"kind": "admin1", "code": "POL-1"},
        {"kind": "admin1", "code": "POL-2"},
    ], "PL", cache_dir)

    assert geom.bounds == (19.0, 49.0, 22.0, 53.0)


def test_morceaux_disjoints_donnent_un_multipolygone(cache_dir):
    geom = resolve_pieces([
        {"kind": "rect", "bounds": [2.0, 48.0, 3.0, 49.0]},
        {"kind": "rect", "bounds": [10.0, 48.0, 11.0, 49.0]},
    ], "PL", cache_dir)

    assert geom.geom_type == "MultiPolygon"
    assert len(geom.geoms) == 2


def test_contour_auto_intersectant_est_repare(cache_dir):
    """Un noeud papillon trace a la souris ne doit pas etre rejete."""
    ring = [[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0]]

    geom = resolve_pieces([{"kind": "polygon", "ring": ring}], "PL", cache_dir)

    assert geom.is_valid
    assert geom.area > 0.0


def test_liste_vide_refusee(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([], "PL", cache_dir)


def test_contour_de_deux_sommets_refuse(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "polygon", "ring": [[2.0, 48.0], [3.0, 48.0]]}], "PL", cache_dir)


def test_coordonnee_hors_bornes_refusee(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "rect", "bounds": [2.0, 48.0, 3.0, 95.0]}], "PL", cache_dir)


def test_coordonnee_non_numerique_refusee(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "rect", "bounds": [2.0, 48.0, "est", 49.0]}], "PL", cache_dir)


def test_rectangle_degenere_refuse(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "rect", "bounds": [2.0, 48.0, 2.0, 49.0]}], "PL", cache_dir)


def test_type_de_morceau_inconnu_refuse(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "cercle", "radius_km": 25}], "PL", cache_dir)


def test_code_de_region_inconnu_refuse(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "admin1", "code": "POL-99"}], "PL", cache_dir)


def test_pays_absent_de_natural_earth_refuse(cache_dir):
    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "country"}], "ZZ", cache_dir)


def test_contour_trop_long_refuse(cache_dir):
    ring = [[float(i) / 1000.0, 48.0 + float(i) / 1000.0] for i in range(2001)]

    with pytest.raises(PieceError):
        resolve_pieces([{"kind": "polygon", "ring": ring}], "PL", cache_dir)
```

- [ ] **Step 2 : Lancer les tests pour les voir échouer**

Run: `uv run pytest tests/test_pieces.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.review.pieces'`

- [ ] **Step 3 : Écrire `cartometa/review/pieces.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from cartometa.geo.admin1 import region_geometry
from cartometa.geo.reference import country_geometry

MIN_RING_POINTS = 3
# Un contour tracé à la souris compte quelques dizaines de sommets. Ce
# plafond n'est pas une limite ergonomique mais un garde-fou : il empêche
# qu'un client incorrect fasse tourner shapely sur une liste sans fin.
MAX_RING_POINTS = 2000


class PieceError(ValueError):
    """Morceau de zone illisible, invalide, ou hors des bornes terrestres."""


def _check_lonlat(lon: Any, lat: Any) -> tuple[float, float]:
    try:
        x, y = float(lon), float(lat)
    except (TypeError, ValueError):
        raise PieceError(f"coordonnée non numérique : ({lon!r}, {lat!r})") from None
    if not (-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0):
        raise PieceError(f"coordonnée hors des bornes WGS84 : ({x}, {y})")
    return x, y


def _rectangle(piece: dict) -> BaseGeometry:
    bounds = piece.get("bounds")
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise PieceError("un rectangle demande bounds = [ouest, sud, est, nord]")
    west, south = _check_lonlat(bounds[0], bounds[1])
    east, north = _check_lonlat(bounds[2], bounds[3])
    # Les deux clics arrivent dans l'ordre où l'humain les a posés, pas dans
    # l'ordre géographique : on normalise plutôt que de refuser.
    west, east = min(west, east), max(west, east)
    south, north = min(south, north), max(south, north)
    if west == east or south == north:
        raise PieceError("rectangle de surface nulle")
    return box(west, south, east, north)


def _contour(piece: dict) -> BaseGeometry:
    ring = piece.get("ring")
    if not isinstance(ring, (list, tuple)):
        raise PieceError("un contour demande ring = [[lon, lat], …]")
    if not (MIN_RING_POINTS <= len(ring) <= MAX_RING_POINTS):
        raise PieceError(
            f"un contour demande entre {MIN_RING_POINTS} et {MAX_RING_POINTS} "
            f"sommets, reçu {len(ring)}"
        )
    points = []
    for vertex in ring:
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 2:
            raise PieceError(f"sommet illisible : {vertex!r}")
        points.append(_check_lonlat(vertex[0], vertex[1]))

    geom = Polygon(points)
    if not geom.is_valid:
        # Un contour tracé à la souris s'auto-intersecte facilement.
        # `buffer(0)` le répare sans trahir l'intention — même traitement
        # que les contours Natural Earth abîmés (cf. country_geometry).
        geom = geom.buffer(0)
    if geom.is_empty or geom.area <= 0.0:
        raise PieceError("contour de surface nulle")
    return geom


def _region(piece: dict, country: str, cache_dir: Path) -> BaseGeometry:
    code = piece.get("code")
    if not isinstance(code, str) or not code:
        raise PieceError("un morceau admin1 demande le code de la région")
    try:
        return region_geometry(country, code, cache_dir)
    except KeyError as exc:
        raise PieceError(str(exc)) from None


def _country(country: str, cache_dir: Path) -> BaseGeometry:
    try:
        return country_geometry(country, cache_dir)
    except KeyError as exc:
        raise PieceError(str(exc)) from None


def resolve_pieces(pieces: list[dict], country: str, cache_dir: Path) -> BaseGeometry:
    """Union des morceaux d'une zone, résolus côté serveur.

    Le client n'envoie que des descripteurs : `{"kind": "country"}` ou
    `{"kind": "admin1", "code": …}` sont résolus ici depuis Natural Earth,
    jamais reçus sous forme de coordonnées. Une silhouette publiée est donc
    toujours celle du référentiel, quoi qu'ait affiché le navigateur.
    """
    if not isinstance(pieces, (list, tuple)) or not pieces:
        raise PieceError("aucun morceau : il n'y a rien à enregistrer")

    geometries = []
    for piece in pieces:
        if not isinstance(piece, dict):
            raise PieceError(f"morceau illisible : {piece!r}")
        kind = piece.get("kind")
        if kind == "country":
            geometries.append(_country(country, cache_dir))
        elif kind == "admin1":
            geometries.append(_region(piece, country, cache_dir))
        elif kind == "rect":
            geometries.append(_rectangle(piece))
        elif kind == "polygon":
            geometries.append(_contour(piece))
        else:
            raise PieceError(f"type de morceau inconnu : {kind!r}")

    union = unary_union(geometries)
    if union.is_empty or not union.is_valid or union.area <= 0.0:
        raise PieceError("l'union des morceaux ne donne aucune surface valide")
    return union
```

- [ ] **Step 4 : Lancer les tests**

Run: `uv run pytest tests/test_pieces.py -v`
Expected: PASS, 17 tests.

- [ ] **Step 5 : Commit**

```bash
git add cartometa/review/pieces.py tests/test_pieces.py
git commit -m "feat: resoudre une liste de morceaux en une geometrie unique

Rectangle, contour libre, region admin-1 et pays entier s'unissent en une
seule emprise. Les silhouettes viennent de Natural Earth cote serveur, pas
du navigateur."
```

---

### Task 4 : Modèle de données et magasin du reviewer

**Files:**
- Modify: `cartometa/models.py`
- Create: `cartometa/review/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `cartometa.atomic_write.write_json_atomic`
- Produces:
  - `models.STATUS_TRACED = "validé"`, `models.STATUS_REJECTED = "rejeté"`, `models.STATUSES`
  - `models.TIER_MANUAL = "manual"`, `models.ORIGIN_PLONKIT = "plonkit"`, `models.ORIGIN_MANUAL = "manual"`
  - `models.MetaRecord` avec le champ `origin: str = ORIGIN_PLONKIT`
  - `models.GeoRecord(id, geometry, pieces, status)` avec `to_feature()` et `from_feature()`
  - `store.CountryPaths(data: Path, country: str)` et ses propriétés `imported_metas`, `manual_dir`, `manual_metas`, `manual_images`, `geo`, `cache`
  - `store.UnknownMetaError`
  - `store.read_json_list(path: Path) -> list[dict]`
  - `store.load_metas(paths) -> list[dict]`
  - `store.load_geo(paths) -> dict[str, GeoRecord]`
  - `store.save_geo(paths, records: dict[str, GeoRecord]) -> None`
  - `store.build_queue(paths, include_all: bool = False) -> dict`
  - `store.set_decision(paths, meta_id, status, geometry, pieces) -> None`
  - `store.clear_decision(paths, meta_id) -> None`

- [ ] **Step 1 : Écrire les tests**

Créer `tests/test_store.py` :

```python
import json

import pytest

from cartometa.models import STATUS_REJECTED, STATUS_TRACED
from cartometa.review.store import (
    CountryPaths,
    UnknownMetaError,
    build_queue,
    clear_decision,
    load_geo,
    load_metas,
    set_decision,
)

CARRE = {"type": "Polygon",
         "coordinates": [[[2.0, 48.0], [3.0, 48.0], [3.0, 49.0], [2.0, 49.0], [2.0, 48.0]]]}


def _meta(meta_id, **extra):
    base = {
        "id": meta_id, "country": "PL", "tier": "regional", "title": f"titre {meta_id}",
        "description": "description", "category": "autre",
        "source_url": f"https://www.plonkit.net/poland#{meta_id}",
        "extracted_at": "2026-07-30T00:00:00+00:00", "image": f"input/{meta_id}.webp",
    }
    base.update(extra)
    return base


@pytest.fixture
def paths(tmp_path):
    p = CountryPaths(tmp_path / "data", "PL")
    p.imported_metas.parent.mkdir(parents=True)
    p.imported_metas.write_text(json.dumps([_meta("aaaa"), _meta("bbbb")]), "utf-8")
    p.manual_metas.parent.mkdir(parents=True)
    p.manual_metas.write_text(json.dumps([
        _meta("man-1a2b", tier="manual", origin="manual",
              image="data/manual/PL/images/man-1a2b.png"),
    ]), "utf-8")
    return p


def test_la_file_fusionne_les_deux_sources(paths):
    queue = build_queue(paths)

    assert [item["id"] for item in queue["items"]] == ["aaaa", "bbbb", "man-1a2b"]


def test_la_file_expose_le_chemin_d_image_en_url(paths):
    queue = build_queue(paths)

    images = {item["id"]: item["image"] for item in queue["items"]}
    assert images["aaaa"] == "/input/aaaa.webp"
    assert images["man-1a2b"] == "/data/manual/PL/images/man-1a2b.png"


def test_la_file_ignore_par_defaut_les_metas_deja_traitees(paths):
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, [{"kind": "rect", "bounds": [2, 48, 3, 49]}])

    queue = build_queue(paths)

    assert [item["id"] for item in queue["items"]] == ["bbbb", "man-1a2b"]
    assert queue["done"] == 1
    assert queue["total"] == 3


def test_une_meta_rejetee_ne_revient_pas_dans_la_file(paths):
    set_decision(paths, "bbbb", STATUS_REJECTED, None, [])

    assert "bbbb" not in {item["id"] for item in build_queue(paths)["items"]}


def test_include_all_rouvre_tout_avec_les_morceaux(paths):
    morceaux = [{"kind": "admin1", "code": "POL-1"}]
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, morceaux)

    queue = build_queue(paths, include_all=True)

    rouverte = next(item for item in queue["items"] if item["id"] == "aaaa")
    assert rouverte["status"] == STATUS_TRACED
    assert rouverte["pieces"] == morceaux


def test_une_meta_jamais_traitee_arrive_sans_statut_ni_morceau(paths):
    item = build_queue(paths)["items"][0]

    assert item["status"] is None
    assert item["pieces"] == []


def test_la_decision_est_relue_a_l_identique(paths):
    morceaux = [{"kind": "rect", "bounds": [2.0, 48.0, 3.0, 49.0]}]
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, morceaux)

    record = load_geo(paths)["aaaa"]

    assert record.geometry == CARRE
    assert record.pieces == morceaux
    assert record.status == STATUS_TRACED


def test_annuler_retire_la_meta_du_fichier(paths):
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, [{"kind": "country"}])

    clear_decision(paths, "aaaa")

    assert "aaaa" not in load_geo(paths)


def test_annuler_une_meta_sans_decision_leve(paths):
    with pytest.raises(UnknownMetaError):
        clear_decision(paths, "aaaa")


def test_decider_sur_une_meta_inconnue_leve(paths):
    with pytest.raises(UnknownMetaError):
        set_decision(paths, "zzzz", STATUS_TRACED, CARRE, [{"kind": "country"}])


def test_statut_inconnu_refuse(paths):
    with pytest.raises(ValueError):
        set_decision(paths, "aaaa", "corrigé", CARRE, [{"kind": "country"}])


def test_pays_sans_fichier_importe(tmp_path):
    """Un pays peut n'avoir que des metas manuelles."""
    paths = CountryPaths(tmp_path / "data", "XX")
    paths.manual_metas.parent.mkdir(parents=True)
    paths.manual_metas.write_text(json.dumps([_meta("man-abcd", country="XX")]), "utf-8")

    assert [m["id"] for m in load_metas(paths)] == ["man-abcd"]


def test_pays_sans_aucune_source(tmp_path):
    assert load_metas(CountryPaths(tmp_path / "data", "XX")) == []
```

- [ ] **Step 2 : Lancer les tests pour les voir échouer**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.review.store'`

- [ ] **Step 3 : Réécrire `cartometa/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

TIER_COUNTRY = "country"
TIER_REGIONAL = "regional"
TIER_SPOT = "spot"
# Une méta saisie à la main ne vient d'aucune section Plonk It : son tier
# n'est qu'un libellé d'affichage, aucune logique n'en dépend.
TIER_MANUAL = "manual"

ORIGIN_PLONKIT = "plonkit"
ORIGIN_MANUAL = "manual"

# Deux statuts, pas quatre : une géométrie présente est par construction
# tracée à la main, il n'y a plus rien d'automatique à distinguer.
STATUS_TRACED = "validé"
STATUS_REJECTED = "rejeté"
STATUSES = (STATUS_TRACED, STATUS_REJECTED)


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
    origin: str = ORIGIN_PLONKIT
    image: str | None = None
    maps_url: str | None = None
    maps_latlon: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GeoRecord:
    """Décision humaine sur une méta : son emprise, et de quoi la rouvrir.

    `pieces` porte les descripteurs tels que l'humain les a posés. C'est ce
    qui permet de rouvrir une méta déjà tracée et d'en retirer un morceau
    sans tout redessiner — la géométrie seule ne se décompose pas.
    """

    id: str
    geometry: dict[str, Any] | None = None
    pieces: list[dict[str, Any]] = field(default_factory=list)
    status: str = STATUS_TRACED

    def to_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": self.geometry,
            "properties": {"id": self.id, "status": self.status, "pieces": self.pieces},
        }

    @classmethod
    def from_feature(cls, feature: dict[str, Any]) -> "GeoRecord":
        props = feature["properties"]
        return cls(
            id=props["id"],
            geometry=feature["geometry"],
            pieces=props.get("pieces", []),
            status=props["status"],
        )
```

- [ ] **Step 4 : Écrire `cartometa/review/store.py`**

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cartometa.atomic_write import write_json_atomic
from cartometa.models import ORIGIN_PLONKIT, STATUSES, GeoRecord


class UnknownMetaError(ValueError):
    """Levée quand un `id` ne correspond à aucune méta connue du pays."""


@dataclass(frozen=True)
class CountryPaths:
    """Les cinq chemins d'un pays, en un seul endroit.

    Deux sources de métas cohabitent : l'import Plonk It, gitignoré parce que
    régénérable, et la saisie manuelle, versionnée parce qu'irremplaçable.
    Les réunir ici évite que chaque appelant réinvente la convention.
    """

    data: Path
    country: str

    @property
    def imported_metas(self) -> Path:
        return self.data / "metas" / f"{self.country}.json"

    @property
    def manual_dir(self) -> Path:
        return self.data / "manual" / self.country

    @property
    def manual_metas(self) -> Path:
        return self.manual_dir / "metas.json"

    @property
    def manual_images(self) -> Path:
        return self.manual_dir / "images"

    @property
    def geo(self) -> Path:
        return self.data / "geo" / f"{self.country}.geojson"

    @property
    def cache(self) -> Path:
        return self.data / "cache"


def read_json_list(path: Path) -> list[dict]:
    """Liste JSON, ou liste vide si le fichier n'existe pas.

    Une source absente n'est pas une erreur : un pays peut n'avoir que des
    métas importées, ou que des métas manuelles.
    """
    if not path.exists():
        return []
    return json.loads(path.read_text("utf-8"))


def load_metas(paths: CountryPaths) -> list[dict]:
    """Métas importées puis manuelles, dans cet ordre."""
    return read_json_list(paths.imported_metas) + read_json_list(paths.manual_metas)


def load_geo(paths: CountryPaths) -> dict[str, GeoRecord]:
    if not paths.geo.exists():
        return {}
    data = json.loads(paths.geo.read_text("utf-8"))
    records = [GeoRecord.from_feature(f) for f in data.get("features", [])]
    return {record.id: record for record in records}


def save_geo(paths: CountryPaths, records: dict[str, GeoRecord]) -> None:
    write_json_atomic(paths.geo, {
        "type": "FeatureCollection",
        "features": [records[key].to_feature() for key in sorted(records)],
    })


def _image_url(meta: dict) -> str | None:
    # Les deux sources stockent un chemin relatif à la racine du projet, que
    # le serveur sert tel quel.
    return "/" + meta["image"] if meta.get("image") else None


def build_queue(paths: CountryPaths, include_all: bool = False) -> dict:
    """File de revue du pays.

    Par défaut, les métas déjà tracées ou rejetées en sont exclues.
    `include_all` les rouvre avec leurs morceaux, pour repasser sur un pays
    quand une nouvelle source donne mieux.
    """
    metas = load_metas(paths)
    geo = load_geo(paths)
    items = []
    for meta in metas:
        record = geo.get(meta["id"])
        if record is not None and not include_all:
            continue
        items.append({
            "id": meta["id"],
            "title": meta["title"],
            "description": meta["description"],
            "category": meta["category"],
            "tier": meta["tier"],
            "origin": meta.get("origin", ORIGIN_PLONKIT),
            "image": _image_url(meta),
            "latlon": meta.get("maps_latlon"),
            "source_url": meta.get("source_url", ""),
            "status": record.status if record is not None else None,
            "pieces": record.pieces if record is not None else [],
        })
    return {
        "country": paths.country,
        "total": len(metas),
        "done": len(geo),
        "items": items,
    }


def set_decision(
    paths: CountryPaths,
    meta_id: str,
    status: str,
    geometry: dict | None,
    pieces: list[dict],
) -> None:
    if status not in STATUSES:
        raise ValueError(f"statut inconnu : {status!r} (attendu {' ou '.join(STATUSES)})")
    if meta_id not in {meta["id"] for meta in load_metas(paths)}:
        raise UnknownMetaError(f"méta inconnue : {meta_id!r}")
    records = load_geo(paths)
    records[meta_id] = GeoRecord(
        id=meta_id, geometry=geometry, pieces=list(pieces), status=status
    )
    save_geo(paths, records)


def clear_decision(paths: CountryPaths, meta_id: str) -> None:
    """Remet une méta à l'état « à faire » en retirant sa décision."""
    records = load_geo(paths)
    if meta_id not in records:
        raise UnknownMetaError(f"aucune décision à annuler pour {meta_id!r}")
    del records[meta_id]
    save_geo(paths, records)
```

- [ ] **Step 5 : Lancer les tests**

Run: `uv run pytest tests/test_store.py tests/test_html_parser.py -v`
Expected: PASS. `test_html_parser.py` vérifie que l'ajout du champ `origin` à `MetaRecord` n'a pas cassé la construction des métas importées.

- [ ] **Step 6 : Commit**

```bash
git add cartometa/models.py cartometa/review/store.py tests/test_store.py
git commit -m "feat: magasin du reviewer sur deux sources de metas

GeoRecord porte desormais les morceaux qui ont servi a tracer l'emprise,
ce qui permet de rouvrir une meta et d'en retirer un seul morceau."
```

---

### Task 5 : Saisie de métas manuelles

**Files:**
- Create: `cartometa/review/manual.py`
- Test: `tests/test_manual_meta.py`

**Interfaces:**
- Consumes: `store.CountryPaths`, `store.read_json_list`, `store.load_metas`, `models.MetaRecord`
- Produces:
  - `manual.ManualMetaError` (sous-classe de `ValueError`)
  - `manual.MAX_IMAGE_BYTES: int`, `manual.CATEGORIES: tuple[str, ...]`
  - `manual.new_meta_id(existing: set[str]) -> str`
  - `manual.create_meta(paths, *, title, description, category, source_url="") -> dict`
  - `manual.save_image(paths, meta_id: str, raw: bytes) -> str` — renvoie le chemin relatif enregistré

- [ ] **Step 1 : Écrire les tests**

Créer `tests/test_manual_meta.py` :

```python
import json
from io import BytesIO

import pytest
from PIL import Image

from cartometa.review.manual import (
    MAX_IMAGE_BYTES,
    ManualMetaError,
    create_meta,
    new_meta_id,
    save_image,
)
from cartometa.review.store import CountryPaths, load_metas, read_json_list


def _png(size=(40, 30), color=(200, 30, 30)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def paths(tmp_path):
    return CountryPaths(tmp_path / "data", "PL")


def _create(paths, **extra):
    champs = {"title": "Bornes jaunes", "description": "Les bornes sont jaunes.",
              "category": "bollards"}
    champs.update(extra)
    return create_meta(paths, **champs)


def test_l_identifiant_est_prefixe(paths):
    meta = _create(paths)

    assert meta["id"].startswith("man-")
    assert len(meta["id"]) == len("man-") + 4


def test_la_meta_est_ecrite_dans_le_fichier_manuel(paths):
    meta = _create(paths)

    enregistrees = read_json_list(paths.manual_metas)
    assert [m["id"] for m in enregistrees] == [meta["id"]]


def test_la_meta_porte_l_origine_manuelle(paths):
    meta = _create(paths)

    assert meta["origin"] == "manual"
    assert meta["tier"] == "manual"
    assert meta["country"] == "PL"


def test_les_metas_s_accumulent(paths):
    _create(paths, title="Une")
    _create(paths, title="Deux")

    assert len(read_json_list(paths.manual_metas)) == 2


def test_identifiant_unique_meme_en_cas_de_collision(monkeypatch):
    tirages = iter(["abcd", "abcd", "ef01"])
    monkeypatch.setattr(
        "cartometa.review.manual.secrets.token_hex", lambda _n: next(tirages)
    )

    assert new_meta_id({"man-abcd"}) == "man-ef01"


def test_titre_vide_refuse(paths):
    with pytest.raises(ManualMetaError):
        _create(paths, title="   ")


def test_description_vide_refusee(paths):
    with pytest.raises(ManualMetaError):
        _create(paths, description="")


def test_categorie_inconnue_refusee(paths):
    with pytest.raises(ManualMetaError):
        _create(paths, category="licornes")


def test_l_image_est_ecrite_sous_un_nom_genere(paths):
    meta = _create(paths)

    save_image(paths, meta["id"], _png())

    assert (paths.manual_images / f"{meta['id']}.png").exists()


def test_l_image_est_rattachee_a_la_meta(paths):
    meta = _create(paths)

    save_image(paths, meta["id"], _png())

    relu = next(m for m in load_metas(paths) if m["id"] == meta["id"])
    assert relu["image"].endswith(f"{meta['id']}.png")


def test_le_format_jpeg_est_accepte(paths):
    meta = _create(paths)
    buffer = BytesIO()
    Image.new("RGB", (10, 10), (0, 0, 0)).save(buffer, format="JPEG")

    save_image(paths, meta["id"], buffer.getvalue())

    assert (paths.manual_images / f"{meta['id']}.jpg").exists()


def test_octets_qui_ne_sont_pas_une_image_refuses(paths):
    meta = _create(paths)

    with pytest.raises(ManualMetaError):
        save_image(paths, meta["id"], b"<?php system($_GET['c']); ?>")


def test_image_trop_lourde_refusee(paths):
    meta = _create(paths)

    with pytest.raises(ManualMetaError):
        save_image(paths, meta["id"], b"\x89PNG" + b"\x00" * MAX_IMAGE_BYTES)


def test_image_pour_une_meta_inconnue_refusee(paths):
    _create(paths)

    with pytest.raises(ManualMetaError):
        save_image(paths, "man-ffff", _png())


def test_aucun_fichier_n_est_ecrit_hors_du_dossier_images(paths):
    """Le nom du fichier vient de l'identifiant serveur, jamais du client."""
    meta = _create(paths)

    save_image(paths, meta["id"], _png())

    ecrits = list(paths.manual_images.iterdir())
    assert [p.name for p in ecrits] == [f"{meta['id']}.png"]
```

- [ ] **Step 2 : Lancer les tests pour les voir échouer**

Run: `uv run pytest tests/test_manual_meta.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.review.manual'`

- [ ] **Step 3 : Écrire `cartometa/review/manual.py`**

```python
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from cartometa.atomic_write import write_json_atomic
from cartometa.models import ORIGIN_MANUAL, TIER_MANUAL, MetaRecord
from cartometa.review.store import CountryPaths, load_metas, read_json_list

# Une capture d'écran collée dépasse rarement le mégaoctet. Le plafond
# n'existe pas pour contraindre l'usage mais pour qu'un client incorrect ne
# puisse pas remplir le disque.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

EXTENSION_BY_FORMAT = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}

CATEGORIES = ("bollards", "poteaux", "vehicule", "vegetation", "signalisation", "autre")


class ManualMetaError(ValueError):
    """Saisie manuelle refusée : champ manquant, ou image inexploitable."""


def new_meta_id(existing: set[str]) -> str:
    """Identifiant `man-xxxx` libre.

    Le préfixe rend toute collision impossible avec les identifiants Plonk
    It, qui font quatre caractères sans préfixe.
    """
    while True:
        candidate = f"man-{secrets.token_hex(2)}"
        if candidate not in existing:
            return candidate


def _required(value: str | None, label: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ManualMetaError(f"{label} est obligatoire")
    return cleaned


def create_meta(
    paths: CountryPaths,
    *,
    title: str | None,
    description: str | None,
    category: str | None,
    source_url: str | None = "",
) -> dict:
    """Crée une méta saisie à la main et l'ajoute au fichier manuel du pays."""
    title = _required(title, "le titre")
    description = _required(description, "la description")
    if category not in CATEGORIES:
        raise ManualMetaError(
            f"catégorie inconnue : {category!r} (attendu {', '.join(CATEGORIES)})"
        )

    meta = MetaRecord(
        # L'unicité se juge sur les DEUX sources : un identifiant libre côté
        # manuel mais déjà pris côté import casserait la fusion.
        id=new_meta_id({m["id"] for m in load_metas(paths)}),
        country=paths.country,
        tier=TIER_MANUAL,
        title=title,
        description=description,
        category=category,
        source_url=(source_url or "").strip(),
        extracted_at=datetime.now(timezone.utc).isoformat(),
        description_origin="manual",
        origin=ORIGIN_MANUAL,
    ).to_dict()

    existing = read_json_list(paths.manual_metas)
    existing.append(meta)
    write_json_atomic(paths.manual_metas, existing)
    return meta


def _relative_to_cwd(path: Path) -> str:
    """Chemin tel que le serveur le sert : relatif à la racine du projet.

    Le serveur sert les fichiers depuis son répertoire de travail, et les
    métas importées y stockent déjà `input/…`. On garde la même convention
    pour que l'interface n'ait qu'une règle : préfixer par `/`.
    """
    root = Path.cwd().resolve()
    absolute = (root / path).resolve()
    if absolute.is_relative_to(root):
        return absolute.relative_to(root).as_posix()
    return absolute.as_posix()


def save_image(paths: CountryPaths, meta_id: str, raw: bytes) -> str:
    """Écrit l'image d'une méta manuelle et la rattache à celle-ci."""
    if len(raw) > MAX_IMAGE_BYTES:
        raise ManualMetaError(
            f"image trop lourde : {len(raw)} octets, maximum {MAX_IMAGE_BYTES}"
        )
    try:
        image = Image.open(BytesIO(raw))
        image_format = image.format
        image.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ManualMetaError("les octets reçus ne forment pas une image lisible") from None
    extension = EXTENSION_BY_FORMAT.get(image_format or "")
    if extension is None:
        raise ManualMetaError(f"format d'image non accepté : {image_format!r}")

    metas = read_json_list(paths.manual_metas)
    target = next((m for m in metas if m["id"] == meta_id), None)
    if target is None:
        raise ManualMetaError(f"méta manuelle inconnue : {meta_id!r}")

    # Le nom du fichier est construit à partir de l'identifiant attribué par
    # le serveur, jamais d'une donnée reçue : écrire ailleurs que dans
    # `images/` est structurellement impossible, pas seulement interdit.
    paths.manual_images.mkdir(parents=True, exist_ok=True)
    destination = paths.manual_images / f"{meta_id}{extension}"
    destination.write_bytes(raw)

    target["image"] = _relative_to_cwd(destination)
    write_json_atomic(paths.manual_metas, metas)
    return target["image"]
```

- [ ] **Step 4 : Lancer les tests**

Run: `uv run pytest tests/test_manual_meta.py -v`
Expected: PASS, 15 tests.

- [ ] **Step 5 : Commit**

```bash
git add cartometa/review/manual.py tests/test_manual_meta.py
git commit -m "feat: saisie de metas manuelles avec image

Le nom du fichier image vient de l'identifiant attribue par le serveur :
aucune donnee client ne touche le chemin d'ecriture."
```

---

### Task 6 : Serveur de revue

**Files:**
- Modify: `cartometa/review/server.py` (réécriture complète)
- Test: `tests/test_review_server.py`

**Interfaces:**
- Consumes: `store.*`, `manual.*`, `pieces.resolve_pieces`, `admin1.country_regions`, `reference.country_geometry`
- Produces:
  - `server.STATE: dict` avec les clés `"paths"` et `"include_all"`
  - `server.apply_decision(meta_id: str, status: str, pieces: list) -> None`
  - `server.Handler`, `server.main()`
  - Routes : `GET /api/queue`, `GET /api/country-polygon`, `GET /api/admin1`, `GET /api/category?text=…`, `POST /api/decision`, `POST /api/undo`, `POST /api/meta`, `POST /api/meta/image?id=…`

`GET /api/category` sert le pré-remplissage de la catégorie dans le formulaire manuel. L'inférence elle-même est déjà couverte par `tests/test_categories.py` : la route n'est qu'un passe-plat, elle ne demande pas son propre test.

- [ ] **Step 1 : Écrire les tests**

Créer `tests/test_review_server.py` :

```python
import json

import pytest
from shapely.geometry import shape

from cartometa.models import STATUS_REJECTED, STATUS_TRACED
from cartometa.review import server
from cartometa.review.pieces import PieceError
from cartometa.review.store import CountryPaths, load_geo


def _box(x0, y0, x1, y1):
    return {"type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


COUNTRIES = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"ISO_A2": "PL", "ISO_A2_EH": "PL", "NAME": "Poland"},
     "geometry": _box(14.0, 49.0, 24.0, 55.0)},
]}


@pytest.fixture
def paths(tmp_path):
    p = CountryPaths(tmp_path / "data", "PL")
    p.imported_metas.parent.mkdir(parents=True)
    p.imported_metas.write_text(json.dumps([{
        "id": "aaaa", "country": "PL", "tier": "regional", "title": "titre",
        "description": "description", "category": "autre", "image": None,
        "source_url": "https://www.plonkit.net/poland#aaaa",
        "extracted_at": "2026-07-30T00:00:00+00:00",
    }]), "utf-8")
    p.cache.mkdir(parents=True)
    (p.cache / "ne_10m_admin_0_countries.geojson").write_text(json.dumps(COUNTRIES), "utf-8")
    server.STATE["paths"] = p
    server.STATE["include_all"] = False
    return p


def test_la_decision_resout_les_morceaux_avant_d_ecrire(paths):
    server.apply_decision("aaaa", STATUS_TRACED, [{"kind": "rect", "bounds": [2, 48, 3, 49]}])

    record = load_geo(paths)["aaaa"]
    assert shape(record.geometry).bounds == (2.0, 48.0, 3.0, 49.0)
    assert record.status == STATUS_TRACED


def test_le_pays_entier_vient_de_natural_earth_pas_du_client(paths):
    """Le client n'envoie qu'un drapeau : la silhouette est relue cote serveur."""
    server.apply_decision("aaaa", STATUS_TRACED, [{"kind": "country"}])

    assert shape(load_geo(paths)["aaaa"].geometry).bounds == (14.0, 49.0, 24.0, 55.0)


def test_les_morceaux_sont_conserves_pour_rouvrir_la_meta(paths):
    morceaux = [{"kind": "rect", "bounds": [2, 48, 3, 49]}, {"kind": "country"}]

    server.apply_decision("aaaa", STATUS_TRACED, morceaux)

    assert load_geo(paths)["aaaa"].pieces == morceaux


def test_un_rejet_n_a_pas_besoin_de_morceaux(paths):
    server.apply_decision("aaaa", STATUS_REJECTED, [])

    record = load_geo(paths)["aaaa"]
    assert record.status == STATUS_REJECTED
    assert record.geometry is None


def test_valider_sans_morceau_est_refuse(paths):
    with pytest.raises(PieceError):
        server.apply_decision("aaaa", STATUS_TRACED, [])


def test_statut_inconnu_refuse(paths):
    with pytest.raises(ValueError):
        server.apply_decision("aaaa", "corrigé", [{"kind": "country"}])


def test_rien_n_est_ecrit_quand_un_morceau_est_invalide(paths):
    with pytest.raises(PieceError):
        server.apply_decision("aaaa", STATUS_TRACED, [{"kind": "rect", "bounds": [2, 48, 3, 999]}])

    assert load_geo(paths) == {}
```

- [ ] **Step 2 : Lancer les tests pour les voir échouer**

Run: `uv run pytest tests/test_review_server.py -v`
Expected: FAIL — `AttributeError` ou `KeyError` sur `server.STATE["paths"]`, l'ancien module n'ayant ni cette clé ni cette signature d'`apply_decision`.

- [ ] **Step 3 : Réécrire `cartometa/review/server.py`**

```python
from __future__ import annotations

import argparse
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from shapely.geometry import mapping

from cartometa.extract.categories import infer_category
from cartometa.geo.admin1 import country_regions
from cartometa.geo.reference import country_geometry
from cartometa.models import STATUS_REJECTED, STATUS_TRACED
from cartometa.review.manual import ManualMetaError, create_meta, save_image
from cartometa.review.pieces import PieceError, resolve_pieces
from cartometa.review.store import (
    CountryPaths,
    UnknownMetaError,
    build_queue,
    clear_decision,
    set_decision,
)

STATIC = Path(__file__).resolve().parent / "static"
STATE: dict = {"paths": None, "include_all": False}

# Même plafond que `manual.MAX_IMAGE_BYTES`, appliqué avant de lire le corps :
# on refuse sur l'en-tête plutôt qu'après avoir absorbé les octets.
MAX_BODY_BYTES = 8 * 1024 * 1024


def paths() -> CountryPaths:
    return STATE["paths"]


def apply_decision(meta_id: str, status: str, pieces: list) -> None:
    """Enregistre une décision, en résolvant les morceaux côté serveur.

    Un rejet ne demande aucune géométrie. Une validation, elle, ne passe
    jamais par la géométrie affichée dans le navigateur : les descripteurs
    sont relus depuis Natural Earth, puis unis. Rien n'est écrit si la
    résolution échoue.
    """
    if status == STATUS_REJECTED:
        set_decision(paths(), meta_id, STATUS_REJECTED, None, [])
        return
    if status != STATUS_TRACED:
        raise ValueError(f"statut inconnu : {status!r}")
    geometry = resolve_pieces(pieces, paths().country, paths().cache)
    set_decision(paths(), meta_id, STATUS_TRACED, mapping(geometry), list(pieces))


class Handler(SimpleHTTPRequestHandler):
    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError(f"corps trop volumineux : {length} octets")
        return self.rfile.read(length) if length else b""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route, query = parsed.path, parse_qs(parsed.query)
        if route == "/api/category":
            # Passe-plat vers l'inférence de l'extraction : le formulaire
            # manuel propose une catégorie plutôt que d'en imposer une.
            text = (query.get("text") or [""])[0]
            self._json({"category": infer_category(text, text)})
            return
        if route == "/api/queue":
            self._json(build_queue(paths(), STATE["include_all"]))
            return
        if route == "/api/country-polygon":
            try:
                geometry = country_geometry(paths().country, paths().cache)
            except KeyError as exc:
                self._json({"ok": False, "error": str(exc)}, 404)
                return
            self._json({"geometry": mapping(geometry)})
            return
        if route == "/api/admin1":
            try:
                self._json(country_regions(paths().country, paths().cache))
            except KeyError as exc:
                self._json({"ok": False, "error": str(exc)}, 404)
            except OSError as exc:
                # Le dataset admin-1 pèse 41 Mo : son premier téléchargement
                # peut échouer, et l'interface doit le dire plutôt que
                # d'attendre un survol qui ne surlignera jamais rien.
                self._json(
                    {"ok": False, "error": f"téléchargement admin-1 impossible : {exc}"}, 502
                )
            return

        if route in ("/", "/index.html"):
            self.path = "/index.html"
            route = "/index.html"
        # Les fichiers de l'interface sont servis depuis `static/` ; tout le
        # reste (images des métas) depuis la racine du projet.
        if (STATIC / route.lstrip("/")).is_file():
            self.directory = str(STATIC)
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route, query = parsed.path, parse_qs(parsed.query)
        try:
            if route == "/api/meta/image":
                meta_id = (query.get("id") or [""])[0]
                stored = save_image(paths(), meta_id, self._body())
                self._json({"ok": True, "image": "/" + stored})
                return

            payload = json.loads(self._body() or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("le corps doit être un objet JSON")

            if route == "/api/decision":
                apply_decision(payload["id"], payload["status"], payload.get("pieces") or [])
            elif route == "/api/undo":
                clear_decision(paths(), payload["id"])
            elif route == "/api/meta":
                meta = create_meta(
                    paths(),
                    title=payload.get("title"),
                    description=payload.get("description"),
                    category=payload.get("category"),
                    source_url=payload.get("source_url", ""),
                )
                self._json({"ok": True, "meta": meta})
                return
            else:
                self.send_error(404)
                return
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "corps JSON invalide"}, 400)
        except KeyError as exc:
            self._json({"ok": False, "error": f"champ manquant : {exc}"}, 400)
        except UnknownMetaError as exc:
            self._json({"ok": False, "error": str(exc)}, 404)
        except (PieceError, ManualMetaError, ValueError) as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # garde-fou : jamais de connexion coupée en silence
            self._json({"ok": False, "error": f"erreur interne : {exc}"}, 500)
        else:
            self._json({"ok": True})

    def log_message(self, *args) -> None:
        pass  # silence : le compteur de progression est dans l'interface


TOUCHES = """Touches — D rectangle, C contour libre, S subdivisions, P pays entier
          Retour arriere retirer le dernier morceau, Echap sortir du mode, 0 vider
          A enregistrer, R rejeter, Espace suivante (Maj+Espace precedente), U annuler
          N nouvelle meta manuelle"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Interface de revue des géométries")
    parser.add_argument("country", nargs="?", default="PL")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Rouvrir toutes les métas, y compris celles déjà tracées ou rejetées.",
    )
    args = parser.parse_args()
    STATE["paths"] = CountryPaths(args.data, args.country.upper())
    STATE["include_all"] = args.all

    print(f"Revue {STATE['paths'].country} : http://127.0.0.1:{args.port}")
    print(TOUCHES)
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4 : Lancer les tests**

Run: `uv run pytest tests/test_review_server.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5 : Commit**

```bash
git add cartometa/review/server.py tests/test_review_server.py
git commit -m "feat: serveur de revue sur les morceaux et les metas manuelles

Le client envoie des descripteurs, jamais des polygones : une silhouette
publiee vient toujours de Natural Earth."
```

---

### Task 7 : Socle de l'interface — appels, géométrie, page

Les tâches 7 à 9 portent le front, pour lequel le dépôt n'a pas de banc de test automatisé (pytest seulement, aucun bundler). La vérification est donc **manuelle et scriptée** : chaque tâche se termine par une liste de gestes à faire dans le navigateur, avec le résultat attendu. Ne pas introduire d'outillage JS : la contrainte « aucun build » est structurante pour ce dépôt.

**Files:**
- Create: `cartometa/review/static/api.js`, `cartometa/review/static/geometry.js`
- Modify: `cartometa/review/static/index.html`

**Interfaces:**
- Consumes: routes de la Task 6
- Produces:
  - `api.js` : `getJSON(path)`, `postJSON(path, body)`, `postBytes(path, blob)`
  - `geometry.js` : `rectangleGeometry(a, b)`, `ringGeometry(points)`, `containsPoint(geometry, lng, lat)`, `bboxOf(geometry)`, `bboxContains(bbox, lng, lat)`

- [ ] **Step 1 : Écrire `cartometa/review/static/api.js`**

```js
// Un seul chemin pour toutes les requêtes : une erreur réseau, un code HTTP
// d'échec et un `{ok: false}` applicatif doivent tous remonter de la même
// façon, sinon l'interface avale des échecs en silence.
async function request(path, options) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (err) {
    throw new Error(`connexion au serveur perdue : ${err.message}`);
  }
  let data = {};
  try {
    data = await response.json();
  } catch (_err) {
    // pas de corps JSON exploitable : on retombe sur le code HTTP
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `erreur HTTP ${response.status}`);
  }
  return data;
}

export const getJSON = (path) => request(path);

export const postJSON = (path, body) => request(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const postBytes = (path, blob) => request(path, { method: 'POST', body: blob });
```

- [ ] **Step 2 : Écrire `cartometa/review/static/geometry.js`**

```js
export function rectangleGeometry(a, b) {
  const [west, east] = [Math.min(a.lng, b.lng), Math.max(a.lng, b.lng)];
  const [south, north] = [Math.min(a.lat, b.lat), Math.max(a.lat, b.lat)];
  return {
    type: 'Polygon',
    coordinates: [[
      [west, south], [east, south], [east, north], [west, north], [west, south],
    ]],
  };
}

export function ringGeometry(points) {
  const ring = points.map((p) => [p.lng, p.lat]);
  return { type: 'Polygon', coordinates: [[...ring, ring[0]]] };
}

export function bboxOf(geometry) {
  let west = 180;
  let south = 90;
  let east = -180;
  let north = -90;
  const scan = (coords) => {
    if (typeof coords[0] === 'number') {
      west = Math.min(west, coords[0]);
      east = Math.max(east, coords[0]);
      south = Math.min(south, coords[1]);
      north = Math.max(north, coords[1]);
    } else {
      coords.forEach(scan);
    }
  };
  scan(geometry.coordinates);
  return [west, south, east, north];
}

export function bboxContains(bbox, x, y) {
  return x >= bbox[0] && x <= bbox[2] && y >= bbox[1] && y <= bbox[3];
}

// Lancer de rayon. Un point sur une frontière peut tomber d'un côté ou de
// l'autre selon l'arrondi : sans conséquence ici, l'humain reclique.
//
// La mise à jour `j = i, i += 1` fait de `j` le sommet PRÉCÉDENT : c'est la
// paire (i, j) qui décrit l'arête. L'écrire `j = i += 1` donnerait à `j` la
// valeur incrémentée et testerait des arêtes de longueur nulle.
function ringContains(ring, x, y) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const straddles = (yi > y) !== (yj > y);
    if (straddles && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function polygonContains(rings, x, y) {
  // Hors de l'anneau extérieur, ou dans un trou : dans les deux cas, dehors.
  if (!ringContains(rings[0], x, y)) return false;
  return !rings.slice(1).some((hole) => ringContains(hole, x, y));
}

export function containsPoint(geometry, x, y) {
  if (geometry.type === 'Polygon') return polygonContains(geometry.coordinates, x, y);
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates.some((rings) => polygonContains(rings, x, y));
  }
  return false;
}
```

- [ ] **Step 3 : Réécrire `cartometa/review/static/index.html`**

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
    #sketch-row { color: #0a7d2b; font-weight: bold; }
    #sketch-row[hidden] { display: none; }
    kbd { background: #eee; border-radius: 3px; padding: 1px 5px; border: 1px solid #bbb; }
    #error { background: #b00020; color: #fff; padding: 8px 12px; font-weight: bold; }
    #error[hidden] { display: none; }
    #manual { position: fixed; inset: 10% 25%; background: #fff; border: 2px solid #1c1f24;
              padding: 16px; overflow: auto; box-shadow: 0 8px 32px rgba(0,0,0,.4); z-index: 1000; }
    #manual[hidden] { display: none; }
    #manual label { display: block; margin: 8px 0 2px; font-weight: bold; }
    #manual input[type=text], #manual textarea, #manual select { width: 100%; font: inherit; }
    #manual textarea { height: 5em; }
    #drop { border: 2px dashed #999; padding: 24px; text-align: center; color: #666;
            margin-top: 8px; }
    #drop.filled { border-color: #0a7d2b; color: #0a7d2b; }
    #drop img { max-height: 120px; display: block; margin: 8px auto 0; }
    #manual-error { color: #b00020; font-weight: bold; }
  </style>
</head>
<body>
  <header>
    <b id="progress">…</b>
    <span id="context"></span>
    <span style="margin-left:auto">
      <kbd>D</kbd> rectangle <kbd>C</kbd> contour <kbd>S</kbd> subdivisions
      <kbd>P</kbd> pays <kbd>⌫</kbd> retirer <kbd>0</kbd> vider
      <kbd>A</kbd> enregistrer <kbd>R</kbd> rejeter <kbd>Espace</kbd> suivante
      <kbd>U</kbd> annuler <kbd>N</kbd> nouvelle méta
    </span>
  </header>
  <div id="error" hidden></div>
  <div id="panes">
    <div id="source"><img id="image" alt=""></div>
    <div id="map"></div>
  </div>
  <div id="info">
    <h2 id="title"></h2>
    <p id="description"></p>
    <p id="sketch-row" hidden></p>
    <a id="source-link" target="_blank" rel="noopener">source</a>
  </div>

  <div id="manual" hidden>
    <h3>Nouvelle méta</h3>
    <label for="manual-title">Titre</label>
    <input id="manual-title" type="text">
    <label for="manual-description">Description</label>
    <textarea id="manual-description"></textarea>
    <label for="manual-category">Catégorie</label>
    <select id="manual-category">
      <option value="bollards">bollards</option>
      <option value="poteaux">poteaux</option>
      <option value="vehicule">vehicule</option>
      <option value="vegetation">vegetation</option>
      <option value="signalisation">signalisation</option>
      <option value="autre" selected>autre</option>
    </select>
    <label for="manual-source">Source (URL, facultatif)</label>
    <input id="manual-source" type="text">
    <div id="drop">Dépose une image ici, ou colle-la avec Ctrl+V</div>
    <p id="manual-error"></p>
    <p>
      <button id="manual-save" type="button">Créer</button>
      <button id="manual-cancel" type="button">Annuler (Échap)</button>
    </p>
  </div>

  <script type="module" src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 4 : Vérifier que les modules sont servis**

Run: `uv run cartometa-review PL --port 8765` puis, dans un autre terminal :

```bash
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:8765/api.js
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:8765/geometry.js
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/
```

Expected: `200 text/javascript` pour les deux modules, `200` pour la page. Arrêter le serveur avec `Ctrl+C`.

- [ ] **Step 5 : Commit**

```bash
git add cartometa/review/static/api.js cartometa/review/static/geometry.js \
        cartometa/review/static/index.html
git commit -m "feat: socle de l'interface de revue en modules ES

api.js centralise la remontee d'erreurs, geometry.js porte la construction
de geometries et le test point-dans-polygone du mode subdivisions."
```

---

### Task 8 : Modes de tracé

**Files:**
- Create: `cartometa/review/static/sketch.js`

**Interfaces:**
- Consumes: `api.js` (`getJSON`), `geometry.js` (tout)
- Produces: `sketch.js` exporte `class Sketch` :
  - `new Sketch(map, layerGroup)`
  - `reset(pieces)` — charge les morceaux d'une méta
  - `async setMode(mode)` — `'rect' | 'contour' | 'admin1' | null`
  - `async addCountry()`
  - `undoLast()`, `clear()`, `leaveMode()`
  - `onMapClick(latlng)`, `onMapMove(latlng) -> boolean` (vrai si l'affichage doit être refait), `closeContour()`
  - champs publics `pieces: Array`, `mode: string | null` ; accesseur `isEmpty`
  - `statusLine() -> string`, `render()`

- [ ] **Step 1 : Écrire `cartometa/review/static/sketch.js`**

```js
import { getJSON } from './api.js';
import {
  bboxContains, bboxOf, containsPoint, rectangleGeometry, ringGeometry,
} from './geometry.js';

const POSE = { color: '#0a7d2b', weight: 2, fillOpacity: 0.25 };
const EN_COURS = { color: '#0a7d2b', weight: 2, dashArray: '5 5', fill: false };
const SURVOL = { color: '#0057d9', weight: 2, fillOpacity: 0.15 };

// Rayon d'accrochage au premier sommet, en pixels écran : c'est le geste qui
// ferme un contour libre.
const FERMETURE_PX = 12;

const NOMS = { rect: 'rectangle', contour: 'contour libre', admin1: 'subdivisions' };

export class Sketch {
  constructor(map, layerGroup) {
    this.map = map;
    this.layers = layerGroup;
    this.pieces = [];
    this.mode = null;
    this.corner = null;     // premier coin d'un rectangle en cours
    this.vertices = [];     // sommets d'un contour en cours
    this.preview = null;    // géométrie élastique suivant le curseur
    this.hovered = null;    // code de la région survolée en mode admin1
    this.country = null;    // silhouette du pays, chargée une fois
    this.regions = null;    // index des régions admin-1, chargé une fois
  }

  get isEmpty() {
    return this.pieces.length === 0;
  }

  reset(pieces) {
    this.pieces = pieces ? pieces.map((piece) => ({ ...piece })) : [];
    this.leaveMode();
  }

  leaveMode() {
    this.mode = null;
    this.corner = null;
    this.vertices = [];
    this.preview = null;
    this.hovered = null;
  }

  clear() {
    this.pieces = [];
    this.leaveMode();
  }

  async setMode(mode) {
    // Changer de mode abandonne le morceau en cours mais garde les posés :
    // c'est le cumul qui est la règle, pas la substitution.
    this.leaveMode();
    if (mode === 'admin1') await this.ensureRegions();
    this.mode = mode;
  }

  async ensureCountry() {
    if (!this.country) this.country = (await getJSON('/api/country-polygon')).geometry;
    return this.country;
  }

  async ensureRegions() {
    if (this.regions) return this.regions;
    const collection = await getJSON('/api/admin1');
    // Une région admin-1 au 1:10m peut compter des dizaines de milliers de
    // sommets. Sans ce filtre par boîte englobante, chaque mouvement de
    // souris relancerait un lancer de rayon sur toutes les régions du pays.
    this.regions = collection.features.map((feature) => ({
      code: feature.properties.code,
      name: feature.properties.name,
      geometry: feature.geometry,
      bbox: bboxOf(feature.geometry),
    }));
    return this.regions;
  }

  async addCountry() {
    await this.ensureCountry();
    this.leaveMode();
    if (!this.pieces.some((piece) => piece.kind === 'country')) {
      this.pieces.push({ kind: 'country' });
    }
  }

  regionAt(latlng) {
    if (!this.regions) return null;
    return this.regions.find(
      (region) => bboxContains(region.bbox, latlng.lng, latlng.lat)
        && containsPoint(region.geometry, latlng.lng, latlng.lat),
    ) || null;
  }

  onMapClick(latlng) {
    if (this.mode === 'rect') {
      if (!this.corner) {
        this.corner = latlng;
        this.preview = null;
      } else {
        this.pieces.push({ kind: 'rect', bounds: boundsOf(this.corner, latlng) });
        this.corner = null;
        this.preview = null;
      }
      return;
    }
    if (this.mode === 'contour') {
      if (this.vertices.length >= 3 && this.nearFirst(latlng)) {
        this.closeContour();
        return;
      }
      this.vertices.push(latlng);
      this.preview = null;
      return;
    }
    if (this.mode === 'admin1') {
      const region = this.regionAt(latlng);
      if (!region) return;
      const already = this.pieces.findIndex(
        (piece) => piece.kind === 'admin1' && piece.code === region.code,
      );
      if (already >= 0) this.pieces.splice(already, 1);
      else this.pieces.push({ kind: 'admin1', code: region.code });
    }
  }

  onMapMove(latlng) {
    if (this.mode === 'rect' && this.corner) {
      this.preview = rectangleGeometry(this.corner, latlng);
      return true;
    }
    if (this.mode === 'contour' && this.vertices.length) {
      this.preview = ringGeometry([...this.vertices, latlng]);
      return true;
    }
    if (this.mode === 'admin1') {
      const region = this.regionAt(latlng);
      const code = region ? region.code : null;
      if (code === this.hovered) return false;
      this.hovered = code;
      return true;
    }
    return false;
  }

  nearFirst(latlng) {
    const first = this.map.latLngToContainerPoint(this.vertices[0]);
    return first.distanceTo(this.map.latLngToContainerPoint(latlng)) <= FERMETURE_PX;
  }

  closeContour() {
    if (this.vertices.length < 3) return;
    this.pieces.push({
      kind: 'polygon',
      ring: this.vertices.map((p) => [p.lng, p.lat]),
    });
    this.vertices = [];
    this.preview = null;
  }

  undoLast() {
    // Contextuel : tant qu'un contour est ouvert, ⌫ défait le dernier
    // sommet. C'est le geste attendu, et sinon un contour raté ne se
    // corrigerait qu'en le recommençant entièrement.
    if (this.mode === 'contour' && this.vertices.length) {
      this.vertices.pop();
      this.preview = null;
      return;
    }
    if (this.mode === 'rect' && this.corner) {
      this.corner = null;
      this.preview = null;
      return;
    }
    this.pieces.pop();
  }

  geometryFor(piece) {
    if (piece.kind === 'rect') {
      const [west, south, east, north] = piece.bounds;
      return {
        type: 'Polygon',
        coordinates: [[
          [west, south], [east, south], [east, north], [west, north], [west, south],
        ]],
      };
    }
    if (piece.kind === 'polygon') {
      return { type: 'Polygon', coordinates: [[...piece.ring, piece.ring[0]]] };
    }
    if (piece.kind === 'country') return this.country;
    const region = (this.regions || []).find((r) => r.code === piece.code);
    return region ? region.geometry : null;
  }

  render() {
    this.pieces.forEach((piece) => {
      const geometry = this.geometryFor(piece);
      if (geometry) L.geoJSON(geometry, POSE).addTo(this.layers);
    });
    if (this.mode === 'admin1' && this.hovered) {
      const region = this.regions.find((r) => r.code === this.hovered);
      const posee = this.pieces.some((p) => p.kind === 'admin1' && p.code === this.hovered);
      if (region && !posee) L.geoJSON(region.geometry, SURVOL).addTo(this.layers);
    }
    if (this.preview) L.geoJSON(this.preview, EN_COURS).addTo(this.layers);
    this.vertices.forEach((vertex, position) => {
      L.circleMarker(vertex, {
        radius: position === 0 ? 6 : 4, color: '#0a7d2b', fillOpacity: 1,
      }).addTo(this.layers);
    });
    if (this.corner) {
      L.circleMarker(this.corner, {
        radius: 4, color: '#0a7d2b', fillOpacity: 1,
      }).addTo(this.layers);
    }
  }

  statusLine() {
    const parts = [];
    if (this.mode) {
      parts.push(`mode ${NOMS[this.mode]}`);
      if (this.mode === 'rect') {
        parts.push(this.corner ? 'clique le coin opposé' : 'clique le premier coin');
      }
      if (this.mode === 'contour') {
        parts.push(this.vertices.length >= 3
          ? 'reclique le premier sommet pour fermer (ou Entrée)'
          : `${this.vertices.length}/3 sommets`);
      }
      if (this.mode === 'admin1') {
        const region = this.regions && this.hovered
          ? this.regions.find((r) => r.code === this.hovered)
          : null;
        parts.push(region ? region.name : 'survole une région');
      }
    }
    if (this.pieces.length) {
      parts.push(`${this.pieces.length} morceau${this.pieces.length > 1 ? 'x' : ''}`);
      parts.push('A enregistrer · ⌫ retirer · 0 vider');
    }
    return parts.join(' — ');
  }
}

function boundsOf(a, b) {
  return [
    Math.min(a.lng, b.lng), Math.min(a.lat, b.lat),
    Math.max(a.lng, b.lng), Math.max(a.lat, b.lat),
  ];
}
```

- [ ] **Step 2 : Vérifier la syntaxe du module**

Run: `uv run python -c "import pathlib; pathlib.Path('cartometa/review/static/sketch.js').read_text('utf-8')"` puis ouvrir la page et vérifier la console.

La vérification réelle a lieu à la Task 9, quand `app.js` câble le module. À ce stade, contrôler seulement qu'aucune accolade ne manque :

Run: `node --check cartometa/review/static/sketch.js` si `node` est disponible ; sinon passer, la Task 9 le révélera dans la console du navigateur.

- [ ] **Step 3 : Commit**

```bash
git add cartometa/review/static/sketch.js
git commit -m "feat: modes de trace cumulables

Rectangle, contour libre et subdivisions posent des morceaux qui
s'accumulent. Le survol en mode subdivisions filtre par boite englobante
avant tout lancer de rayon."
```

---

### Task 9 : File, clavier et formulaire manuel

**Files:**
- Create: `cartometa/review/static/manual.js`
- Modify: `cartometa/review/static/app.js` (réécriture complète)

**Interfaces:**
- Consumes: `api.js`, `sketch.js` (`Sketch`)
- Produces:
  - `manual.js` : `openManualForm(onCreated)`, `closeManualForm()`, `isManualFormOpen()`
  - `app.js` : point d'entrée, aucun export

- [ ] **Step 1 : Écrire `cartometa/review/static/manual.js`**

```js
import { getJSON, postBytes, postJSON } from './api.js';

const panel = document.getElementById('manual');
const drop = document.getElementById('drop');
const errorLine = document.getElementById('manual-error');
const categorySelect = document.getElementById('manual-category');

let pendingImage = null;   // Blob en attente, envoyé après création de la méta
let onCreated = null;
// Dès que l'humain a choisi une catégorie, l'inférence se tait : proposer
// est utile, écraser un choix explicite ne l'est jamais.
let categoryTouched = false;
let inferTimer = null;

export function isManualFormOpen() {
  return !panel.hidden;
}

export function openManualForm(callback) {
  onCreated = callback;
  pendingImage = null;
  categoryTouched = false;
  errorLine.textContent = '';
  drop.className = '';
  drop.innerHTML = 'Dépose une image ici, ou colle-la avec Ctrl+V';
  ['manual-title', 'manual-description', 'manual-source'].forEach((id) => {
    document.getElementById(id).value = '';
  });
  categorySelect.value = 'autre';
  panel.hidden = false;
  document.getElementById('manual-title').focus();
}

function scheduleInference() {
  if (categoryTouched) return;
  clearTimeout(inferTimer);
  inferTimer = setTimeout(async () => {
    const text = `${document.getElementById('manual-title').value} `
      + `${document.getElementById('manual-description').value}`;
    if (!text.trim()) return;
    try {
      const guessed = await getJSON(`/api/category?text=${encodeURIComponent(text)}`);
      // Retest après l'aller-retour : l'humain a pu choisir entre-temps.
      if (!categoryTouched) categorySelect.value = guessed.category;
    } catch (_err) {
      // Deviner la catégorie est un confort : son échec ne bloque rien.
    }
  }, 400);
}

export function closeManualForm() {
  panel.hidden = true;
  pendingImage = null;
}

function showImage(blob) {
  pendingImage = blob;
  drop.className = 'filled';
  drop.innerHTML = 'Image prête';
  const preview = document.createElement('img');
  preview.src = URL.createObjectURL(blob);
  drop.appendChild(preview);
}

async function save() {
  errorLine.textContent = '';
  const body = {
    title: document.getElementById('manual-title').value,
    description: document.getElementById('manual-description').value,
    category: categorySelect.value,
    source_url: document.getElementById('manual-source').value,
  };
  let meta;
  try {
    meta = (await postJSON('/api/meta', body)).meta;
  } catch (err) {
    errorLine.textContent = err.message;
    return;
  }
  if (pendingImage) {
    try {
      // La méta existe déjà : si le dépôt d'image échoue, on ne la perd pas,
      // on le signale et l'humain pourra la compléter.
      const stored = await postBytes(`/api/meta/image?id=${meta.id}`, pendingImage);
      meta.image = stored.image;
    } catch (err) {
      errorLine.textContent = `Méta créée, mais image refusée : ${err.message}`;
      return;
    }
  }
  closeManualForm();
  if (onCreated) onCreated(meta);
}

document.getElementById('manual-save').addEventListener('click', save);
document.getElementById('manual-cancel').addEventListener('click', closeManualForm);
categorySelect.addEventListener('change', () => { categoryTouched = true; });
['manual-title', 'manual-description'].forEach((id) => {
  document.getElementById(id).addEventListener('input', scheduleInference);
});

drop.addEventListener('dragover', (event) => event.preventDefault());
drop.addEventListener('drop', (event) => {
  event.preventDefault();
  const file = event.dataTransfer.files[0];
  if (file && file.type.startsWith('image/')) showImage(file);
});

document.addEventListener('paste', (event) => {
  if (!isManualFormOpen()) return;
  const item = [...(event.clipboardData?.items || [])]
    .find((candidate) => candidate.type.startsWith('image/'));
  if (!item) return;
  event.preventDefault();
  showImage(item.getAsFile());
});
```

- [ ] **Step 2 : Réécrire `cartometa/review/static/app.js`**

```js
import { getJSON, postJSON } from './api.js';
import { Sketch } from './sketch.js';
import { closeManualForm, isManualFormOpen, openManualForm } from './manual.js';

const map = L.map('map').setView([52, 19], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 18,
}).addTo(map);

// Les touches pilotent le tracé, pas la carte.
map.keyboard.disable();

const layers = L.layerGroup().addTo(map);
const sketch = new Sketch(map, layers);

let queue = [];
let index = 0;
let total = 0;
let done = 0;
let busy = false;
// Chaque entrée est { type: 'decision', id } ou { type: 'pass' }, dans
// l'ordre exact des actions — U doit défaire précisément la dernière.
let history = [];

const current = () => queue[index];

function showError(message) {
  const el = document.getElementById('error');
  el.textContent = message;
  el.hidden = false;
}

function clearError() {
  const el = document.getElementById('error');
  el.hidden = true;
  el.textContent = '';
}

async function loadQueue() {
  const data = await getJSON('/api/queue');
  queue = data.items;
  total = data.total;
  done = data.done;
  index = 0;
  history = [];
  render();
}

function render() {
  const item = current();
  layers.clearLayers();
  if (!item) {
    document.getElementById('progress').textContent = `Terminé — ${done} / ${total}`;
    document.getElementById('title').textContent = '';
    document.getElementById('description').textContent = '';
    document.getElementById('image').removeAttribute('src');
    document.getElementById('sketch-row').hidden = true;
    return;
  }
  document.getElementById('progress').textContent = `${done + index} / ${total}`;
  document.getElementById('context').textContent =
    `${item.category} — ${item.tier}${item.status ? ` — ${item.status}` : ''}`;
  if (item.image) document.getElementById('image').src = item.image;
  else document.getElementById('image').removeAttribute('src');
  document.getElementById('title').textContent = item.title;
  document.getElementById('description').textContent = item.description;
  document.getElementById('source-link').href = item.source_url || '#';

  sketch.reset(item.pieces);
  frame(item);
  draw();
}

async function frame(item) {
  // Tout arrive vierge : le point Maps est le seul repère quand il existe,
  // sinon on cadre le pays pour ne pas laisser la carte au milieu de rien.
  if (item.latlon) {
    map.setView([item.latlon[0], item.latlon[1]], 8);
    return;
  }
  try {
    const geometry = await sketch.ensureCountry();
    map.fitBounds(L.geoJSON(geometry).getBounds(), { padding: [20, 20] });
  } catch (err) {
    showError(`Cadrage impossible : ${err.message}`);
  }
}

function draw() {
  const item = current();
  layers.clearLayers();
  if (!item) return;
  sketch.render();
  if (item.latlon) {
    // Vérité terrain : elle ne bouge pas, c'est la cible.
    L.circleMarker([item.latlon[0], item.latlon[1]], {
      radius: 6, color: '#0057d9', fillOpacity: 0.9,
    }).addTo(layers);
  }
  const row = document.getElementById('sketch-row');
  row.textContent = sketch.statusLine();
  row.hidden = !row.textContent;
}

async function decide(status) {
  const item = current();
  if (!item || busy) return;
  if (status === 'validé' && sketch.isEmpty) {
    showError('Aucun morceau posé : rien à enregistrer.');
    return;
  }
  busy = true;
  try {
    await postJSON('/api/decision', {
      id: item.id, status, pieces: status === 'validé' ? sketch.pieces : [],
    });
    clearError();
    history.push({ type: 'decision', id: item.id });
    done += 1;
    index += 1;
    render();
  } catch (err) {
    // Échec : l'index n'avance pas, la méta reste affichée, l'erreur visible.
    showError(`Décision non enregistrée pour ${item.id} : ${err.message}`);
  } finally {
    busy = false;
  }
}

async function undo() {
  if (!history.length || busy) return;
  const last = history[history.length - 1];
  if (last.type === 'pass') {
    // Un passage n'a rien persisté : on le défait sans appel réseau.
    history.pop();
    index = Math.max(0, index - 1);
    render();
    return;
  }
  busy = true;
  try {
    await postJSON('/api/undo', { id: last.id });
    clearError();
    history.pop();
    done = Math.max(0, done - 1);
    index = Math.max(0, index - 1);
    render();
  } catch (err) {
    showError(`Annulation impossible pour ${last.id} : ${err.message}`);
  } finally {
    busy = false;
  }
}

function step(offset) {
  if (busy || !current()) return;
  if (offset > 0) history.push({ type: 'pass' });
  index = Math.min(Math.max(0, index + offset), queue.length);
  render();
}

async function enterMode(mode) {
  if (busy || !current()) return;
  try {
    await sketch.setMode(mode);
    clearError();
  } catch (err) {
    showError(`Mode ${mode} indisponible : ${err.message}`);
  }
  draw();
}

async function addCountry() {
  if (busy || !current()) return;
  try {
    await sketch.addCountry();
    clearError();
  } catch (err) {
    showError(`Polygone du pays indisponible : ${err.message}`);
  }
  draw();
}

function onManualCreated(meta) {
  // La méta créée passe devant : on la trace tout de suite, tant qu'on a
  // sa source sous les yeux.
  queue.splice(index, 0, {
    id: meta.id, title: meta.title, description: meta.description,
    category: meta.category, tier: meta.tier, origin: meta.origin,
    image: meta.image || null, latlon: null, source_url: meta.source_url,
    status: null, pieces: [],
  });
  total += 1;
  render();
}

document.addEventListener('keydown', (event) => {
  if (isManualFormOpen()) {
    if (event.key === 'Escape') closeManualForm();
    return;
  }
  if (event.key === 'Backspace') {
    event.preventDefault();
    sketch.undoLast();
    draw();
    return;
  }
  if (event.key === 'Escape') {
    sketch.leaveMode();
    draw();
    return;
  }
  if (event.key === 'Enter') {
    sketch.closeContour();
    draw();
    return;
  }
  if (event.key === ' ') {
    event.preventDefault();
    step(event.shiftKey ? -1 : 1);
    return;
  }
  switch (event.key.toLowerCase()) {
    case 'd': enterMode('rect'); break;
    case 'c': enterMode('contour'); break;
    case 's': enterMode('admin1'); break;
    case 'p': addCountry(); break;
    case '0': sketch.clear(); draw(); break;
    case 'a': decide('validé'); break;
    case 'r': decide('rejeté'); break;
    case 'u': undo(); break;
    case 'n': openManualForm(onManualCreated); break;
    default: break;
  }
});

map.on('click', (event) => {
  if (busy || !current()) return;
  sketch.onMapClick(event.latlng);
  draw();
});

map.on('mousemove', (event) => {
  if (!sketch.mode) return;
  if (sketch.onMapMove(event.latlng)) draw();
});

loadQueue().catch((err) => showError(`File indisponible : ${err.message}`));
```

- [ ] **Step 3 : Vérification manuelle sur un pays réel**

Lancer `uv run cartometa-review PL`, ouvrir <http://127.0.0.1:8765>, et dérouler cette liste. Chaque ligne attend le résultat indiqué ; toute divergence est un bug à corriger avant de committer.

1. La page charge, une méta s'affiche, la console ne montre aucune erreur.
2. `D` puis deux clics → un rectangle vert apparaît, la barre d'état dit `1 morceau`.
3. Deux clics de plus → **deux** rectangles, la barre dit `2 morceaux` (le mode est collant).
4. `⌫` → un seul rectangle reste.
5. `C` puis quatre clics, puis clic sur le premier sommet → le contour se ferme en vert plein.
6. `C` puis deux clics, puis `⌫` → le dernier sommet disparaît, pas le rectangle posé.
7. `S` → au survol, la région sous le curseur se surligne en bleu et son nom s'affiche dans la barre d'état. Le survol reste fluide.
8. Clic sur une région → elle passe en vert. Reclic → elle disparaît.
9. `P` → la silhouette du pays s'ajoute aux morceaux existants.
10. `0` → tout disparaît, la barre d'état se vide.
11. `A` sur une zone vide → message d'erreur rouge « Aucun morceau posé », l'index n'avance pas.
12. Poser un rectangle puis `A` → la méta suivante s'affiche, le compteur avance.
13. `U` → la méta précédente revient, le compteur recule.
14. `R` → la méta suivante s'affiche sans qu'aucune géométrie ait été demandée.
15. `N` → le formulaire s'ouvre ; taper « Yellow bollards » dans le titre → la catégorie bascule seule sur `bollards` ; la changer à la main pour `autre` puis continuer à taper → elle ne rebascule plus.
16. Dans le même formulaire, `Ctrl+V` sur une capture d'écran affiche l'aperçu ; « Créer » ferme le panneau et affiche la nouvelle méta, image comprise.
17. Vérifier sur disque : `data/manual/PL/metas.json` contient la méta, `data/manual/PL/images/man-*.png` existe.
18. Arrêter le serveur, relancer avec `--all` → les métas déjà tracées reviennent avec leurs morceaux affichés.

- [ ] **Step 4 : Commit**

```bash
git add cartometa/review/static/app.js cartometa/review/static/manual.js
git commit -m "feat: file, clavier et formulaire de meta manuelle

Les modes de trace sont collants, la file s'ouvre sur les metas restantes
et --all rouvre celles deja tracees avec leurs morceaux."
```

---

### Task 10 : Export, migration et documentation

**Files:**
- Modify: `cartometa/geo/export.py:8`, `:36-57`
- Modify: `tests/test_export.py`, `tests/test_real_data.py`
- Modify: `README.md`, `docs/rapport-pologne.md`
- Delete: `data/calib/`
- Rewrite: tous les `data/geo/*.geojson`

**Interfaces:**
- Consumes: `store.CountryPaths`, `store.load_metas`, `models.STATUS_TRACED`
- Produces: `export.EXPORTABLE = ("validé",)`, `export.export_viewer(data_dir, out_dir, countries)` sans paramètre `include_auto`

- [ ] **Step 1 : Adapter les tests d'export**

Remplacer, dans `tests/test_export.py`, le helper `_write_country` et les fixtures pour refléter le nouveau format. Le fichier complet devient :

```python
import json
from pathlib import Path

import pytest

from cartometa.geo.export import discover_countries, export_viewer


def _square(x: float, y: float, size: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y],
        ]],
    }


def _meta(meta_id: str, tier: str = "regional") -> dict:
    return {
        "id": meta_id, "tier": tier, "title": f"titre {meta_id}",
        "description": "description", "category": "autre",
        "image": f"input/{meta_id}.webp",
        "source_url": f"https://www.plonkit.net/x#{meta_id}",
    }


def _write_country(data_dir: Path, country: str, entries: list[tuple[str, str, float]]) -> None:
    """entries: (id, statut, taille du carré) — la taille pilote l'ordre de tri."""
    (data_dir / "metas").mkdir(parents=True, exist_ok=True)
    (data_dir / "geo").mkdir(parents=True, exist_ok=True)
    (data_dir / "metas" / f"{country}.json").write_text(
        json.dumps([_meta(i) for i, _, _ in entries]), "utf-8"
    )
    (data_dir / "geo" / f"{country}.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {"id": i, "status": status, "pieces": [{"kind": "country"}]},
             "geometry": _square(0.0, 0.0, size) if status == "validé" else None}
            for i, status, size in entries
        ],
    }), "utf-8")


@pytest.fixture
def data_dir(tmp_path):
    _write_country(tmp_path / "data", "PL", [("pl1", "validé", 3.0), ("pl2", "rejeté", 1.0)])
    _write_country(tmp_path / "data", "BW", [("bw1", "validé", 2.0)])
    return tmp_path / "data"


def test_seules_les_metas_tracees_sont_exportees(data_dir, tmp_path):
    export_viewer(data_dir, tmp_path / "viewer", ["PL", "BW"])

    index = json.loads((tmp_path / "viewer" / "data" / "index.json").read_text("utf-8"))
    assert {entry["id"] for entry in index} == {"pl1", "bw1"}


def test_l_index_est_trie_par_surface_croissante(data_dir, tmp_path):
    export_viewer(data_dir, tmp_path / "viewer", ["PL", "BW"])

    index = json.loads((tmp_path / "viewer" / "data" / "index.json").read_text("utf-8"))
    assert [entry["id"] for entry in index] == ["bw1", "pl1"]


def test_les_geometries_sont_ecrites_par_identifiant(data_dir, tmp_path):
    export_viewer(data_dir, tmp_path / "viewer", ["PL", "BW"])

    geometries = json.loads(
        (tmp_path / "viewer" / "data" / "geometries.json").read_text("utf-8")
    )
    assert set(geometries) == {"pl1", "bw1"}


def test_les_metas_manuelles_sont_exportees(tmp_path):
    data_dir = tmp_path / "data"
    _write_country(data_dir, "XX", [])
    manual = data_dir / "manual" / "XX"
    manual.mkdir(parents=True)
    (manual / "metas.json").write_text(json.dumps([
        dict(_meta("man-1a2b", tier="manual"), origin="manual",
             image="data/manual/XX/images/man-1a2b.png"),
    ]), "utf-8")
    (data_dir / "geo" / "XX.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "man-1a2b", "status": "validé",
                                     "pieces": [{"kind": "country"}]},
                      "geometry": _square(0.0, 0.0, 1.0)}],
    }), "utf-8")

    export_viewer(data_dir, tmp_path / "viewer", ["XX"])

    index = json.loads((tmp_path / "viewer" / "data" / "index.json").read_text("utf-8"))
    assert [entry["id"] for entry in index] == ["man-1a2b"]


def test_pays_sans_aucune_meta_leve(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "geo").mkdir(parents=True)
    (data_dir / "geo" / "ZZ.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": [],
    }), "utf-8")

    with pytest.raises(SystemExit):
        export_viewer(data_dir, tmp_path / "viewer", ["ZZ"])


def test_discover_countries_trie_et_met_en_majuscules(data_dir):
    assert discover_countries(data_dir) == ["BW", "PL"]
```

- [ ] **Step 2 : Lancer les tests pour les voir échouer**

Run: `uv run pytest tests/test_export.py -v`
Expected: FAIL — `test_les_metas_manuelles_sont_exportees` et `test_pays_sans_aucune_meta_leve` échouent, l'export exigeant encore `data/metas/<CC>.json`.

- [ ] **Step 3 : Adapter `cartometa/geo/export.py`**

Remplacer la constante et la boucle de lecture :

```python
from cartometa.models import STATUS_TRACED
from cartometa.review.store import CountryPaths, load_metas

EXPORTABLE = (STATUS_TRACED,)
```

Remplacer la signature et le corps de `export_viewer` :

```python
def export_viewer(data_dir: Path, out_dir: Path, countries: list[str]) -> dict:
    """Exporte les données du viewer public.

    Seules les métas tracées à la main sortent : le statut `rejeté` et
    l'absence de décision ne publient rien. Les deux sources de métas —
    import Plonk It et saisie manuelle — sont fusionnées à la lecture.
    """
    index, geometries = [], {}
    by_country: dict[str, int] = {}
    for country in countries:
        paths = CountryPaths(data_dir, country)
        metas = {m["id"]: m for m in load_metas(paths)}
        if not metas:
            raise SystemExit(
                f"{country}: géométries présentes mais aucune méta.\n"
                f"Les textes Plonk It ne sont pas versionnés — régénère-les avec "
                f"cartometa-extract, ou vérifie {paths.manual_metas}."
            )
        geo = json.loads(paths.geo.read_text("utf-8"))
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
            by_country[country] = by_country.get(country, 0) + 1

    index.sort(key=lambda entry: entry["area"])
    target = out_dir / "data"
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.json").write_text(json.dumps(index, ensure_ascii=False), "utf-8")
    (target / "geometries.json").write_text(json.dumps(geometries, ensure_ascii=False), "utf-8")
    return {
        "exported": len(index),
        "countries": countries,
        "by_country": {c: by_country.get(c, 0) for c in countries},
        "output": str(target),
    }
```

Dans `main()`, supprimer l'argument `--include-auto`, l'appel qui le passe, et le bloc `if result["unreviewed_included"]`. L'appel devient `export_viewer(args.data, args.out, countries)`.

- [ ] **Step 4 : Lancer les tests d'export**

Run: `uv run pytest tests/test_export.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5 : Réécrire `tests/test_real_data.py`**

L'ancien fichier teste la sortie du pipeline supprimé. Le remplacer entièrement :

```python
import json
from pathlib import Path

import pytest
from shapely.geometry import shape

pytestmark = pytest.mark.real_data

GEO_DIR = Path("data/geo")
STATUTS = {"validé", "rejeté"}


def _fichiers():
    fichiers = sorted(GEO_DIR.glob("*.geojson"))
    if not fichiers:
        pytest.skip("aucune géométrie : lancer cartometa-review")
    return fichiers


def test_toute_geometrie_enregistree_est_valide():
    for chemin in _fichiers():
        for feature in json.loads(chemin.read_text("utf-8"))["features"]:
            if feature["geometry"] is None:
                continue
            geom = shape(feature["geometry"])
            assert geom.is_valid, f"{chemin.name}: {feature['properties']['id']}"
            assert not geom.is_empty


def test_seuls_les_deux_statuts_prevus_existent():
    for chemin in _fichiers():
        for feature in json.loads(chemin.read_text("utf-8"))["features"]:
            statut = feature["properties"]["status"]
            assert statut in STATUTS, f"{chemin.name}: statut inattendu {statut!r}"


def test_une_meta_tracee_a_toujours_une_geometrie_et_ses_morceaux():
    for chemin in _fichiers():
        for feature in json.loads(chemin.read_text("utf-8"))["features"]:
            props = feature["properties"]
            if props["status"] != "validé":
                continue
            assert feature["geometry"] is not None, f"{chemin.name}: {props['id']}"
            assert props["pieces"], f"{chemin.name}: {props['id']} sans morceau"


def test_une_meta_rejetee_ne_porte_aucune_geometrie():
    for chemin in _fichiers():
        for feature in json.loads(chemin.read_text("utf-8"))["features"]:
            props = feature["properties"]
            if props["status"] == "rejeté":
                assert feature["geometry"] is None, f"{chemin.name}: {props['id']}"
```

- [ ] **Step 6 : Exécuter la table rase**

```bash
uv run python - <<'PY'
import json
from pathlib import Path

vide = {"type": "FeatureCollection", "features": []}
for chemin in sorted(Path("data/geo").glob("*.geojson")):
    chemin.write_text(json.dumps(vide, indent=2, ensure_ascii=False), "utf-8")
    print("vidé:", chemin)
PY
git rm -r --quiet data/calib
```

Run: `uv run pytest -m real_data -v`
Expected: PASS (les fichiers existent mais sont vides, les boucles ne trouvent rien à contredire).

- [ ] **Step 7 : Réécrire la documentation**

Dans `README.md` :

- Supprimer entièrement la section `### 3. Générer les polygones` et son tableau des tiers.
- Renuméroter : « Revoir à la main » devient l'étape 3, « Publier vers le viewer » l'étape 4.
- Remplacer le tableau des touches et les paragraphes qui suivent par :

```markdown
### 3. Tracer les emprises à la main

```
uv run cartometa-review <CC>
```

Sert une interface sur <http://127.0.0.1:8765> (boucle locale uniquement).
Chaque méta arrive **sans géométrie** : c'est à toi de dessiner son emprise.

| Touche | Action |
|---|---|
| `D` | mode rectangle — deux clics posent un morceau |
| `C` | mode contour libre — clics successifs, fermeture en repassant sur le premier sommet ou par `Entrée` |
| `S` | mode subdivisions — chaque clic ajoute/retire la région administrative de niveau 1 sous le curseur |
| `P` | ajoute la silhouette du pays entier |
| `Retour arrière` | retire le dernier morceau, ou le dernier sommet si un contour est en cours |
| `Échap` | sort du mode de dessin sans rien effacer |
| `0` | vide la zone en cours |
| `A` | enregistre l'union des morceaux |
| `R` | rejette la méta |
| `Espace` / `Maj+Espace` | méta suivante / précédente |
| `U` | annule la dernière décision |
| `N` | saisir une méta manuelle (texte + image collée ou déposée) |

Les modes sont **collants** : après un rectangle posé, poser le suivant ne
demande aucune touche. Une emprise est l'union de ses morceaux — deux
rectangles disjoints, trois régions, un contour libre plus le pays entier.

Le point bleu, quand il est présent, est la **vérité terrain** : la position
du lien Maps de la méta.

`cartometa-review <CC> --all` rouvre toutes les métas, y compris celles déjà
tracées, avec leurs morceaux — pour repasser sur un pays quand une nouvelle
source donne mieux.

Le mode subdivisions télécharge au premier usage le jeu de données Natural
Earth admin-1 (41 Mo), puis en extrait les régions du pays dans
`data/cache/admin1/`. Les lancements suivants sont instantanés.
```

- Dans « Où sont les choses », remplacer les lignes de `cartometa/geo/` et `data/calib/` par :

```
cartometa/extract/   HTML → métas structurées, résolution des liens Maps
cartometa/geo/       référentiel Natural Earth (pays, régions) et export
cartometa/review/    serveur local de revue + interface de tracé
viewer/              carte statique (Leaflet, sans build)
data/geo/            emprises tracées + statut + morceaux (versionnés)
data/manual/         métas saisies à la main, textes et images (versionnées)
data/metas/          textes Plonk It (jamais versionnés, régénérables)
input/               pages sauvegardées (jamais versionnées)
docs/                specs, plans, rapports
```

- Dans la section d'export : supprimer la mention de `--include-auto`, et remplacer « un nouveau pays entre dans le viewer dès que `cartometa-geo` a tourné » par « un nouveau pays entre dans le viewer dès qu'une de ses métas a été tracée ». Ces deux phrases sont les dernières occurrences de `cartometa-geo` et `--include-auto` dans le dépôt ; l'étape 8 le vérifie par `grep`.
- Remplacer la section « État » par :

```markdown
## État

Détection automatique retirée le 2026-07-30 : les emprises sont désormais
tracées à la main. Les géométries produites par l'ancien pipeline ont été
effacées et sont à refaire — elles restent consultables dans l'historique
git. `docs/rapport-pologne.md` décrit le pipeline supprimé, conservé comme
trace historique.
```

Dans `docs/rapport-pologne.md`, insérer en tête :

```markdown
> **Document historique.** Ce rapport mesure le pipeline de détection
> automatique de polygones, retiré du dépôt le 2026-07-30. Il ne décrit plus
> le fonctionnement de Cartometa ; il est conservé pour la trace des mesures.
```

- [ ] **Step 8 : Lancer la suite complète**

Run: `uv run pytest`
Expected: PASS. Aucun test ne référence `cartometa-geo`, `confidence`, `warnings`, ni le statut `auto`.

Run: `grep -rn "cartometa-geo\|include_auto\|include-auto\|confidence\|warnings" --include=*.py --include=*.md --include=*.js --include=*.toml cartometa tests viewer README.md pyproject.toml`
Expected: aucun résultat.

- [ ] **Step 9 : Commit**

```bash
git add -A
git commit -m "feat: export sur statut unique, table rase et documentation

Seules les emprises tracees a la main sont exportees, et les metas
manuelles rejoignent les metas importees. Les geometries de l'ancien
pipeline sont effacees : elles restent dans l'historique git."
```

---

## Vérification finale

- [ ] `uv run pytest` — vert
- [ ] `uv run cartometa-extract poland` — inchangé, écrit `data/metas/PL.json`
- [ ] `uv run cartometa-review PL` — la liste de gestes de la Task 9, Step 3, repassée intégralement
- [ ] `uv run cartometa-export` — n'exporte que les métas tracées
- [ ] `python -m http.server 8010` puis <http://127.0.0.1:8010/viewer/> — la carte affiche les métas retracées
- [ ] `git status` — `data/manual/` est suivi par git, `data/metas/` ne l'est pas
