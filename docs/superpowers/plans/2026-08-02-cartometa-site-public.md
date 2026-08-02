# Cartometa — site public : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformer le viewer local en site statique public, déployable en une commande, dont le chargement initial pèse moins de 100 Ko au lieu de 41 Mo.

**Architecture:** Une commande `cartometa-build` produit un dossier `dist/` autonome et gitignoré. Les géométries sont simplifiées, découpées par pays et chargées à la demande ; un index global léger porte les bbox et permet de savoir quel pays télécharger au clic. Tous les fichiers portent une empreinte de contenu, ce qui rend le cache immuable et n'invalide que ce qui change.

**Tech Stack:** Python 3.14, Shapely 2.1, Pillow 12.3, pytest 9.1. Front en JS modules sans build, Leaflet 1.9.4 depuis unpkg.

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-08-02-cartometa-site-public-design.md`.
- Tous les commentaires, docstrings, noms de tests et messages utilisateur sont **en français**, comme le reste du dépôt.
- **Aucun test ne touche le réseau.** Les tests sur données réelles portent le marqueur `real_data`.
- Empreinte de contenu = **8 premiers caractères hexadécimaux du SHA-256** des octets écrits.
- Tolérance de simplification par défaut : `0.01`, **adaptative** — `min(tolérance, diagonale de la bbox / 50)`.
- Précision des coordonnées : **5 décimales**.
- Images : vignette **600 px**, pleine **1400 px**, webp qualité **78**, jamais agrandies.
- Seul le statut `validé` (`STATUS_TRACED`) est publié.
- Adresse de contact : `psmague@gmail.com`.
- Attribution obligatoire sur toutes les pages : `Textes et images © 2021-2026 Plonk It, CC BY-NC-SA 4.0 · Imagery © Google · Fond © OpenStreetMap`.
- L'adaptation mobile est **hors périmètre**.

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `cartometa/build/__init__.py` | paquet vide |
| `cartometa/build/geometry.py` | arrondi, tolérance adaptative, simplification, mesures de contrôle |
| `cartometa/build/dataset.py` | lecture des sources, découpage par pays, index global |
| `cartometa/build/assets.py` | empreintes de contenu, écriture de fichiers nommés par empreinte |
| `cartometa/build/images.py` | redimensionnement et réencodage webp en deux tailles |
| `cartometa/build/site.py` | orchestration, manifeste, `_headers`, comptage des fichiers |
| `cartometa/build/cli.py` | analyse des arguments, résumé à l'écran |
| `viewer/index.html` | structure de la page |
| `viewer/style.css` | habillage clair neutre |
| `viewer/app.js` | carte, chargement paresseux, galerie, filtres, agrandissement |
| `viewer/licence.html` | page de licence |
| `tests/test_build_geometry.py` | tâche 1 |
| `tests/test_build_dataset.py` | tâche 2 |
| `tests/test_build_assets.py` | tâche 3 |
| `tests/test_build_images.py` | tâche 4 |
| `tests/test_build_site.py` | tâches 5 et 8 |

Supprimés en tâche 5 : `cartometa/geo/export.py`, `tests/test_export.py`.

**Note sur le front :** le dépôt n'a aucune infrastructure de test JavaScript et ce plan n'en introduit pas — ce serait un chantier à part entière. Les tâches 6 et 7 sont donc vérifiées par un test Python d'intégrité du `dist/` produit (tout chemin référencé existe) plus une liste de contrôle manuelle explicite. C'est une limite assumée, pas un oubli.

---

### Task 1: Simplification des géométries

**Files:**
- Create: `cartometa/build/__init__.py`
- Create: `cartometa/build/geometry.py`
- Test: `tests/test_build_geometry.py`

**Interfaces:**
- Consumes: rien.
- Produces: `DEFAULT_TOLERANCE: float`, `COORD_PRECISION: int`, `SIZE_DIVISOR: int`, `round_coordinates(geometry: dict, precision: int = COORD_PRECISION) -> dict`, `effective_tolerance(geometry: dict, tolerance: float, divisor: int = SIZE_DIVISOR) -> float`, `simplify_geometry(geometry: dict, tolerance: float = DEFAULT_TOLERANCE, precision: int = COORD_PRECISION) -> dict`, `area_ratio(original: dict, simplified: dict) -> float`, `hausdorff(original: dict, simplified: dict) -> float`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_build_geometry.py` :

```python
import math

import pytest

from cartometa.build.geometry import (
    DEFAULT_TOLERANCE,
    area_ratio,
    effective_tolerance,
    hausdorff,
    round_coordinates,
    simplify_geometry,
)


def _rectangle(x: float, y: float, largeur: float, hauteur: float, pas: int = 1) -> dict:
    """Rectangle dont les côtés portent `pas` sommets intermédiaires alignés.

    Les points intermédiaires sont exactement colinéaires : Douglas-Peucker
    doit les retirer quelle que soit la tolérance, ce qui donne un résultat
    prévisible sans dépendre des données réelles.
    """
    bas = [(x + largeur * i / pas, y) for i in range(pas)]
    droite = [(x + largeur, y + hauteur * i / pas) for i in range(pas)]
    haut = [(x + largeur - largeur * i / pas, y + hauteur) for i in range(pas)]
    gauche = [(x, y + hauteur - hauteur * i / pas) for i in range(pas)]
    anneau = bas + droite + haut + gauche
    anneau.append(anneau[0])
    return {"type": "Polygon", "coordinates": [[list(p) for p in anneau]]}


def test_l_arrondi_ramene_a_cinq_decimales():
    geometrie = {"type": "Polygon", "coordinates": [[
        [1.123456789, 2.987654321], [3.0, 2.0], [3.0, 4.0], [1.123456789, 2.987654321],
    ]]}

    arrondie = round_coordinates(geometrie)

    assert arrondie["coordinates"][0][0] == [1.12346, 2.98765]


def test_la_tolerance_est_plafonnee_par_la_taille_de_l_emprise():
    """Une emprise « spot » de 0,005° ne doit pas recevoir une tolérance de 0,01."""
    minuscule = _rectangle(35.51, 33.88, 0.005, 0.0035)

    tolerance = effective_tolerance(minuscule, DEFAULT_TOLERANCE)

    diagonale = math.hypot(0.005, 0.0035)
    assert tolerance == pytest.approx(diagonale / 50)
    assert tolerance < DEFAULT_TOLERANCE


def test_une_grande_emprise_recoit_la_tolerance_pleine():
    vaste = _rectangle(0.0, 0.0, 10.0, 10.0)

    assert effective_tolerance(vaste, DEFAULT_TOLERANCE) == DEFAULT_TOLERANCE


def test_la_simplification_retire_les_sommets_colineaires():
    dense = _rectangle(0.0, 0.0, 10.0, 10.0, pas=20)
    sommets_avant = len(dense["coordinates"][0])

    simplifiee = simplify_geometry(dense)

    assert len(simplifiee["coordinates"][0]) < sommets_avant


def test_la_simplification_preserve_l_aire_des_petites_emprises():
    """Le cas qui motive la tolérance adaptative : sans elle, on tombait à 24 %."""
    minuscule = _rectangle(35.51, 33.88, 0.005, 0.0035, pas=6)

    simplifiee = simplify_geometry(minuscule)

    assert area_ratio(minuscule, simplifiee) > 0.80


def test_la_simplification_ne_vide_jamais_une_geometrie():
    minuscule = _rectangle(35.51, 33.88, 0.0005, 0.0005, pas=4)

    simplifiee = simplify_geometry(minuscule)

    assert simplifiee["coordinates"][0]
    assert area_ratio(minuscule, simplifiee) > 0.0


def test_la_distance_de_hausdorff_reste_sous_la_tolerance_effective():
    dense = _rectangle(0.0, 0.0, 10.0, 10.0, pas=20)

    simplifiee = simplify_geometry(dense)

    assert hausdorff(dense, simplifiee) <= DEFAULT_TOLERANCE * 2


def test_un_multipolygone_est_simplifie_partie_par_partie():
    multi = {"type": "MultiPolygon", "coordinates": [
        _rectangle(0.0, 0.0, 5.0, 5.0, pas=10)["coordinates"][0],
        _rectangle(20.0, 20.0, 5.0, 5.0, pas=10)["coordinates"][0],
    ]}

    simplifiee = simplify_geometry(multi)

    assert simplifiee["type"] == "MultiPolygon"
    assert len(simplifiee["coordinates"]) == 2
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_build_geometry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.build'`

- [ ] **Step 3: Écrire l'implémentation minimale**

Créer `cartometa/build/__init__.py` (fichier vide).

Créer `cartometa/build/geometry.py` :

```python
from __future__ import annotations

import math

from shapely.geometry import mapping, shape
from shapely.ops import transform

# ~1,1 km à l'équateur. Invisible sur une emprise du type « ce poteau se
# trouve dans cette région », qui est ce que décrivent les métas.
DEFAULT_TOLERANCE = 0.01
# ~1 m. En deçà, on stocke du bruit de flottant.
COORD_PRECISION = 5
# La tolérance ne dépasse jamais la diagonale de l'emprise divisée par ce
# nombre. Sans ce plafond, une tolérance fixe de 0,01° est plus grande que
# les emprises « spot » (~0,005° de côté) et les ampute : mesuré sur les
# données réelles, la pire n'en gardait que 24 % de sa surface.
SIZE_DIVISOR = 50


def round_coordinates(geometry: dict, precision: int = COORD_PRECISION) -> dict:
    """Arrondit toutes les coordonnées, sans toucher à la topologie."""
    arrondi = transform(
        lambda x, y, z=None: (round(x, precision), round(y, precision)),
        shape(geometry),
    )
    return mapping(arrondi)


def effective_tolerance(
    geometry: dict, tolerance: float, divisor: int = SIZE_DIVISOR
) -> float:
    """Tolérance plafonnée par la taille propre de l'emprise."""
    min_lon, min_lat, max_lon, max_lat = shape(geometry).bounds
    diagonale = math.hypot(max_lon - min_lon, max_lat - min_lat)
    return min(tolerance, diagonale / divisor)


def simplify_geometry(
    geometry: dict,
    tolerance: float = DEFAULT_TOLERANCE,
    precision: int = COORD_PRECISION,
) -> dict:
    """Simplifie puis arrondit.

    Dans cet ordre : arrondir d'abord ferait travailler Douglas-Peucker sur
    des sommets déjà déplacés. En cas de dégénérescence — géométrie vide ou
    invalide, ce que la simplification topologique peut produire sur des
    formes pathologiques — on retombe sur l'original arrondi plutôt que de
    publier une emprise fausse.
    """
    original = shape(geometry)
    simplifiee = original.simplify(
        effective_tolerance(geometry, tolerance), preserve_topology=True
    )
    if simplifiee.is_empty or not simplifiee.is_valid or simplifiee.area == 0:
        return round_coordinates(geometry, precision)
    return round_coordinates(mapping(simplifiee), precision)


def area_ratio(original: dict, simplified: dict) -> float:
    """Part de la surface conservée, entre 0 et 1 (au-delà si elle a grossi)."""
    aire = shape(original).area
    if aire == 0:
        return 1.0
    return shape(simplified).area / aire


def hausdorff(original: dict, simplified: dict) -> float:
    """Écart maximal entre les deux contours, en degrés."""
    return shape(original).hausdorff_distance(shape(simplified))
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_build_geometry.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add cartometa/build/__init__.py cartometa/build/geometry.py tests/test_build_geometry.py
git commit -m "feat: simplification des geometries a tolerance adaptative"
```

---

### Task 2: Découpage par pays et index global

**Files:**
- Create: `cartometa/build/dataset.py`
- Test: `tests/test_build_dataset.py`

**Interfaces:**
- Consumes: `simplify_geometry`, `DEFAULT_TOLERANCE` (tâche 1) ; `CountryPaths`, `load_metas` (`cartometa.review.store`) ; `STATUS_TRACED`, `STATUSES` (`cartometa.models`).
- Produces: `Dataset` (attributs `index: list[list]`, `countries: dict[str, dict]`, `legacy_statuses: int`), `build_dataset(data_dir: Path, countries: list[str], tolerance: float = DEFAULT_TOLERANCE) -> Dataset`, `discover_countries(data_dir: Path) -> list[str]`.

Chaque entrée de `index` est `[id, pays, minLon, minLat, maxLon, maxLat, surface]`. Chaque valeur de `countries` est `{"metas": {id: {...}}, "geometries": {id: {...}}}`, où chaque méta porte `title`, `description`, `category`, `source_url` et `image_source` (chemin sur disque, remplacé par `thumb`/`full` en tâche 5).

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_build_dataset.py` :

```python
import json
from pathlib import Path

import pytest

from cartometa.build.dataset import build_dataset, discover_countries


def _carre(x: float, y: float, cote: float) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [x, y], [x + cote, y], [x + cote, y + cote], [x, y + cote], [x, y],
    ]]}


def _meta(meta_id: str) -> dict:
    return {
        "id": meta_id, "tier": "regional", "title": f"titre {meta_id}",
        "description": "description", "category": "autre",
        "image": f"input/{meta_id}.webp",
        "source_url": f"https://www.plonkit.net/x#{meta_id}",
    }


def _ecrire_pays(data_dir: Path, pays: str, entrees: list[tuple[str, str, float]]) -> None:
    (data_dir / "metas").mkdir(parents=True, exist_ok=True)
    (data_dir / "geo").mkdir(parents=True, exist_ok=True)
    (data_dir / "metas" / f"{pays}.json").write_text(
        json.dumps([_meta(i) for i, _, _ in entrees]), "utf-8"
    )
    (data_dir / "geo" / f"{pays}.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {"id": i, "status": statut, "pieces": []},
             "geometry": _carre(0.0, 0.0, cote) if statut == "validé" else None}
            for i, statut, cote in entrees
        ],
    }), "utf-8")


@pytest.fixture
def data_dir(tmp_path):
    _ecrire_pays(tmp_path / "data", "PL", [("pl1", "validé", 3.0), ("pl2", "rejeté", 1.0)])
    _ecrire_pays(tmp_path / "data", "BW", [("bw1", "validé", 2.0)])
    return tmp_path / "data"


def test_seules_les_metas_validees_entrent_dans_le_jeu(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    assert {entree[0] for entree in jeu.index} == {"pl1", "bw1"}


def test_l_index_est_trie_par_surface_croissante(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    assert [entree[0] for entree in jeu.index] == ["bw1", "pl1"]


def test_chaque_meta_est_dans_le_fichier_de_son_pays_et_nulle_part_ailleurs(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    assert set(jeu.countries["PL"]["geometries"]) == {"pl1"}
    assert set(jeu.countries["BW"]["geometries"]) == {"bw1"}


def test_l_index_et_les_fichiers_pays_portent_exactement_les_memes_identifiants(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    depuis_index = {entree[0] for entree in jeu.index}
    depuis_pays = {i for pays in jeu.countries.values() for i in pays["geometries"]}
    assert depuis_index == depuis_pays


def test_l_index_porte_la_bbox_et_le_pays(data_dir):
    jeu = build_dataset(data_dir, ["BW"])

    identifiant, pays, min_lon, min_lat, max_lon, max_lat, surface = jeu.index[0]
    assert (identifiant, pays) == ("bw1", "BW")
    assert (min_lon, min_lat, max_lon, max_lat) == (0.0, 0.0, 2.0, 2.0)
    assert surface == pytest.approx(4.0)


def test_la_meta_porte_le_chemin_de_son_image_source(data_dir):
    jeu = build_dataset(data_dir, ["BW"])

    assert jeu.countries["BW"]["metas"]["bw1"]["image_source"] == "input/bw1.webp"


def test_un_pays_sans_meta_validee_est_absent_du_resultat(tmp_path):
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0)])
    (data_dir / "geo" / "BD.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []}), "utf-8"
    )

    jeu = build_dataset(data_dir, ["BD", "PL"])

    assert set(jeu.countries) == {"PL"}


def test_les_statuts_herites_sont_comptes_et_non_publies(tmp_path):
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "LG", [("lg1", "validé", 1.0)])
    chemin = data_dir / "geo" / "LG.geojson"
    geo = json.loads(chemin.read_text("utf-8"))
    geo["features"].append({
        "type": "Feature",
        "properties": {"id": "lg2", "status": "auto", "pieces": []},
        "geometry": _carre(5.0, 5.0, 1.0),
    })
    chemin.write_text(json.dumps(geo), "utf-8")
    (data_dir / "metas" / "LG.json").write_text(
        json.dumps([_meta("lg1"), _meta("lg2")]), "utf-8"
    )

    jeu = build_dataset(data_dir, ["LG"])

    assert jeu.legacy_statuses == 1
    assert set(jeu.countries["LG"]["geometries"]) == {"lg1"}


def test_geometries_presentes_mais_aucune_meta_leve(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "geo").mkdir(parents=True)
    (data_dir / "geo" / "ZZ.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "zz1", "status": "validé", "pieces": []},
                      "geometry": _carre(0.0, 0.0, 1.0)}],
    }), "utf-8")

    with pytest.raises(SystemExit, match=r"metas\.json"):
        build_dataset(data_dir, ["ZZ"])


def test_discover_countries_trie_et_met_en_majuscules(data_dir):
    assert discover_countries(data_dir) == ["BW", "PL"]
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_build_dataset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.build.dataset'`

- [ ] **Step 3: Écrire l'implémentation minimale**

Créer `cartometa/build/dataset.py` :

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import shape

from cartometa.build.geometry import DEFAULT_TOLERANCE, simplify_geometry
from cartometa.models import STATUS_TRACED, STATUSES
from cartometa.review.store import CountryPaths, load_metas

EXPORTABLE = (STATUS_TRACED,)


@dataclass
class Dataset:
    """Le jeu publiable, découpé.

    `index` est global et léger : il suffit à savoir, au clic, quels pays
    valent la peine d'être téléchargés. `countries` porte le détail, un
    fichier par pays.
    """

    index: list[list] = field(default_factory=list)
    countries: dict[str, dict] = field(default_factory=dict)
    legacy_statuses: int = 0


def discover_countries(data_dir: Path) -> list[str]:
    """Tous les pays ayant un fichier de géométries, par ordre alphabétique."""
    return sorted({p.stem.upper() for p in (data_dir / "geo").glob("*.geojson")})


def build_dataset(
    data_dir: Path, countries: list[str], tolerance: float = DEFAULT_TOLERANCE
) -> Dataset:
    """Lit les sources, simplifie, découpe par pays et construit l'index."""
    jeu = Dataset()
    for pays in countries:
        chemins = CountryPaths(data_dir, pays)
        if not chemins.geo.exists():
            continue
        geo = json.loads(chemins.geo.read_text("utf-8"))
        jeu.legacy_statuses += sum(
            1 for f in geo["features"] if f["properties"]["status"] not in STATUSES
        )
        publiables = [
            f for f in geo["features"]
            if f["properties"]["status"] in EXPORTABLE and f["geometry"]
        ]
        if not publiables:
            # Géojson vide ou tout en `rejeté` : rien à publier, ce n'est pas
            # une erreur. Un clone frais est exactement dans ce cas.
            continue
        metas = {m["id"]: m for m in load_metas(chemins)}
        if not metas:
            raise SystemExit(
                f"{pays} : géométries présentes mais aucune méta.\n"
                f"Les textes Plonk It ne sont pas versionnés — régénère-les avec "
                f"cartometa-extract, ou vérifie {chemins.manual_metas}."
            )
        entree_pays = {"metas": {}, "geometries": {}}
        for feature in publiables:
            identifiant = feature["properties"]["id"]
            meta = metas.get(identifiant)
            if meta is None:
                continue
            geometrie = simplify_geometry(feature["geometry"], tolerance)
            forme = shape(geometrie)
            min_lon, min_lat, max_lon, max_lat = forme.bounds
            jeu.index.append([
                identifiant, pays,
                round(min_lon, 4), round(min_lat, 4),
                round(max_lon, 4), round(max_lat, 4),
                round(forme.area, 6),
            ])
            entree_pays["geometries"][identifiant] = geometrie
            entree_pays["metas"][identifiant] = {
                "title": meta["title"],
                "description": meta["description"],
                "category": meta["category"],
                "source_url": meta["source_url"],
                "image_source": meta.get("image"),
            }
        if entree_pays["geometries"]:
            jeu.countries[pays] = entree_pays
    # Trié par surface croissante : le viewer affiche du plus spécifique au
    # plus général sans avoir à trier lui-même.
    jeu.index.sort(key=lambda entree: entree[6])
    return jeu
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_build_dataset.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add cartometa/build/dataset.py tests/test_build_dataset.py
git commit -m "feat: decoupage par pays et index global des emprises"
```

---

### Task 3: Empreintes de contenu

**Files:**
- Create: `cartometa/build/assets.py`
- Test: `tests/test_build_assets.py`

**Interfaces:**
- Consumes: rien.
- Produces: `HASH_LENGTH: int`, `content_hash(payload: bytes) -> str`, `hashed_name(stem: str, suffix: str, payload: bytes) -> str`, `write_hashed(directory: Path, stem: str, suffix: str, payload: bytes) -> str`.

`write_hashed` crée `directory` au besoin, écrit le fichier et renvoie **son seul nom**, pas son chemin — l'appelant compose l'URL relative.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_build_assets.py` :

```python
from cartometa.build.assets import HASH_LENGTH, content_hash, hashed_name, write_hashed


def test_l_empreinte_fait_huit_caracteres_hexadecimaux():
    empreinte = content_hash(b"peu importe")

    assert len(empreinte) == HASH_LENGTH == 8
    assert all(c in "0123456789abcdef" for c in empreinte)


def test_le_meme_contenu_donne_la_meme_empreinte():
    assert content_hash(b"identique") == content_hash(b"identique")


def test_un_contenu_different_donne_une_empreinte_differente():
    assert content_hash(b"un") != content_hash(b"deux")


def test_le_nom_insere_l_empreinte_entre_la_base_et_l_extension():
    nom = hashed_name("index", ".json", b"contenu")

    assert nom.startswith("index.")
    assert nom.endswith(".json")
    assert nom == f"index.{content_hash(b'contenu')}.json"


def test_write_hashed_ecrit_le_fichier_et_renvoie_son_nom(tmp_path):
    nom = write_hashed(tmp_path / "data", "index", ".json", b'{"a":1}')

    assert (tmp_path / "data" / nom).read_bytes() == b'{"a":1}'
    assert "/" not in nom


def test_deux_ecritures_du_meme_contenu_donnent_le_meme_nom(tmp_path):
    premier = write_hashed(tmp_path, "c", ".json", b"pareil")
    second = write_hashed(tmp_path, "c", ".json", b"pareil")

    assert premier == second


def test_modifier_le_contenu_change_le_nom(tmp_path):
    premier = write_hashed(tmp_path, "c", ".json", b"avant")
    second = write_hashed(tmp_path, "c", ".json", b"apres")

    assert premier != second
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_build_assets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.build.assets'`

- [ ] **Step 3: Écrire l'implémentation minimale**

Créer `cartometa/build/assets.py` :

```python
from __future__ import annotations

import hashlib
from pathlib import Path

# Huit caractères hexadécimaux : 4 milliards de valeurs, largement assez pour
# quelques milliers de fichiers, et un nom qui reste lisible dans une URL.
HASH_LENGTH = 8


def content_hash(payload: bytes) -> str:
    """Empreinte courte du contenu, base du cache immuable."""
    return hashlib.sha256(payload).hexdigest()[:HASH_LENGTH]


def hashed_name(stem: str, suffix: str, payload: bytes) -> str:
    """`index` + `.json` + contenu → `index.a1b2c3d4.json`."""
    return f"{stem}.{content_hash(payload)}{suffix}"


def write_hashed(directory: Path, stem: str, suffix: str, payload: bytes) -> str:
    """Écrit le fichier sous son nom empreinté et renvoie ce nom.

    Renvoie le nom seul et non le chemin : c'est l'appelant qui sait sous
    quelle URL relative le fichier sera servi.
    """
    directory.mkdir(parents=True, exist_ok=True)
    nom = hashed_name(stem, suffix, payload)
    (directory / nom).write_bytes(payload)
    return nom
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_build_assets.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add cartometa/build/assets.py tests/test_build_assets.py
git commit -m "feat: empreintes de contenu pour le cache immuable"
```

---

### Task 4: Images en deux tailles

**Files:**
- Create: `cartometa/build/images.py`
- Test: `tests/test_build_images.py`

**Interfaces:**
- Consumes: `write_hashed` (tâche 3).
- Produces: `THUMB_WIDTH: int`, `FULL_WIDTH: int`, `QUALITY: int`, `MissingImageError`, `render_image_pair(source: Path, out_dir: Path, stem: str) -> dict[str, str]` renvoyant `{"thumb": "<nom>", "full": "<nom>"}`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_build_images.py` :

```python
import pytest
from PIL import Image

from cartometa.build.images import (
    FULL_WIDTH,
    THUMB_WIDTH,
    MissingImageError,
    render_image_pair,
)


def _image(chemin, largeur, hauteur):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (largeur, hauteur), (120, 90, 60)).save(chemin)
    return chemin


def test_les_deux_tailles_sont_produites(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1920, 950)

    noms = render_image_pair(source, tmp_path / "out", "a")

    assert set(noms) == {"thumb", "full"}
    for nom in noms.values():
        assert (tmp_path / "out" / nom).exists()


def test_la_vignette_et_la_pleine_respectent_leur_largeur(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1920, 950)

    noms = render_image_pair(source, tmp_path / "out", "a")

    with Image.open(tmp_path / "out" / noms["thumb"]) as vignette:
        assert vignette.width == THUMB_WIDTH
    with Image.open(tmp_path / "out" / noms["full"]) as pleine:
        assert pleine.width == FULL_WIDTH


def test_une_image_plus_petite_que_la_cible_n_est_jamais_agrandie(tmp_path):
    source = _image(tmp_path / "src" / "petite.png", 400, 200)

    noms = render_image_pair(source, tmp_path / "out", "petite")

    with Image.open(tmp_path / "out" / noms["full"]) as pleine:
        assert pleine.width == 400


def test_la_sortie_est_du_webp(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1000, 500)

    noms = render_image_pair(source, tmp_path / "out", "a")

    assert noms["full"].endswith(".webp")
    with Image.open(tmp_path / "out" / noms["full"]) as pleine:
        assert pleine.format == "WEBP"


def test_les_noms_portent_une_empreinte_et_se_distinguent(tmp_path):
    source = _image(tmp_path / "src" / "a.png", 1000, 500)

    noms = render_image_pair(source, tmp_path / "out", "a")

    assert noms["thumb"] != noms["full"]
    assert noms["thumb"].startswith("a.t.")
    assert noms["full"].startswith("a.f.")


def test_une_source_absente_leve_une_erreur_explicite(tmp_path):
    with pytest.raises(MissingImageError, match="introuvable"):
        render_image_pair(tmp_path / "absente.png", tmp_path / "out", "x")
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_build_images.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.build.images'`

- [ ] **Step 3: Écrire l'implémentation minimale**

Créer `cartometa/build/images.py` :

```python
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from cartometa.build.assets import write_hashed

# La galerie affiche les vignettes autour de 300 px de large ; 600 couvre les
# écrans à densité double sans gaspiller.
THUMB_WIDTH = 600
# Plancher, pas confort : ce sont des montages à plusieurs panneaux annotés,
# illisibles en dessous.
FULL_WIDTH = 1400
QUALITY = 78


class MissingImageError(FileNotFoundError):
    """Levée quand une méta référence une image absente du disque."""


def _encode(image: Image.Image, largeur: int) -> bytes:
    copie = image.copy()
    # `thumbnail` ne fait que réduire : une source plus petite que la cible
    # est laissée telle quelle, jamais interpolée vers le haut.
    copie.thumbnail((largeur, largeur * 10), Image.LANCZOS)
    tampon = io.BytesIO()
    copie.save(tampon, "WEBP", quality=QUALITY, method=4)
    return tampon.getvalue()


def render_image_pair(source: Path, out_dir: Path, stem: str) -> dict[str, str]:
    """Produit la vignette et la pleine taille, et renvoie leurs deux noms."""
    if not source.exists():
        raise MissingImageError(f"image introuvable : {source}")
    with Image.open(source) as image:
        image = image.convert("RGB")
        vignette = _encode(image, THUMB_WIDTH)
        pleine = _encode(image, FULL_WIDTH)
    return {
        "thumb": write_hashed(out_dir, f"{stem}.t", ".webp", vignette),
        "full": write_hashed(out_dir, f"{stem}.f", ".webp", pleine),
    }
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_build_images.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add cartometa/build/images.py tests/test_build_images.py
git commit -m "feat: images en deux tailles webp"
```

---

### Task 5: Orchestration du build, manifeste et en-têtes

**Files:**
- Create: `cartometa/build/site.py`
- Create: `cartometa/build/cli.py`
- Modify: `pyproject.toml:16-19` (scripts)
- Delete: `cartometa/geo/export.py`, `tests/test_export.py`
- Test: `tests/test_build_site.py`

**Interfaces:**
- Consumes: `build_dataset`, `discover_countries` (tâche 2) ; `write_hashed` (tâche 3) ; `render_image_pair`, `MissingImageError` (tâche 4) ; `DEFAULT_TOLERANCE` (tâche 1).
- Produces: `FILE_COUNT_WARNING: int`, `FILE_COUNT_LIMIT: int`, `IMAGE_BASE: str`, `HEADERS: str`, `build_site(data_dir: Path, out_dir: Path, viewer_dir: Path, countries: list[str], tolerance: float = DEFAULT_TOLERANCE, skip_images: bool = False, image_base: str = IMAGE_BASE) -> dict`, `main() -> None`.

Les images sont **toujours écrites dans `out_dir / IMAGE_BASE`** ; `image_base` ne
change que le préfixe inscrit au manifeste. Passer une URL absolue produit donc
un `dist/img/` prêt à être synchronisé vers un bucket, et un site qui pointe
déjà dessus.

`build_site` renvoie `{"metas": int, "countries": dict[str, int], "files": int, "legacy_statuses": int, "output": str}`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_build_site.py` :

```python
import json
from pathlib import Path

import pytest
from PIL import Image

from cartometa.build.site import FILE_COUNT_LIMIT, FILE_COUNT_WARNING, build_site


def _carre(x: float, y: float, cote: float) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [x, y], [x + cote, y], [x + cote, y + cote], [x, y + cote], [x, y],
    ]]}


@pytest.fixture
def projet(tmp_path):
    """Un projet minimal mais complet : données, images sources, gabarits."""
    data = tmp_path / "data"
    (data / "metas").mkdir(parents=True)
    (data / "geo").mkdir(parents=True)
    images = tmp_path / "input"
    images.mkdir()
    Image.new("RGB", (1000, 500), (10, 20, 30)).save(images / "pl1.png")
    (data / "metas" / "PL.json").write_text(json.dumps([{
        "id": "pl1", "tier": "regional", "title": "titre", "description": "desc",
        "category": "autre", "image": "input/pl1.png",
        "source_url": "https://www.plonkit.net/poland#pl1",
    }]), "utf-8")
    (data / "geo" / "PL.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "pl1", "status": "validé", "pieces": []},
                      "geometry": _carre(14.0, 49.0, 5.0)}],
    }), "utf-8")

    viewer = tmp_path / "viewer"
    viewer.mkdir()
    (viewer / "index.html").write_text("<!doctype html><body>__CSS__ __JS__</body>", "utf-8")
    (viewer / "licence.html").write_text("<!doctype html><body>__CSS__</body>", "utf-8")
    (viewer / "style.css").write_text("body{margin:0}", "utf-8")
    (viewer / "app.js").write_text("console.log('x')", "utf-8")
    return tmp_path


def _manifeste(dist: Path) -> dict:
    return json.loads((dist / "data" / "manifest.json").read_text("utf-8"))


def test_le_manifeste_reference_des_fichiers_qui_existent(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    assert (dist / "data" / manifeste["index"]).exists()
    for entree in manifeste["countries"].values():
        assert (dist / "data" / entree["file"]).exists()


def test_toute_image_referencee_existe(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    base = manifeste["image_base"]
    for entree in manifeste["countries"].values():
        pays = json.loads((dist / "data" / entree["file"]).read_text("utf-8"))
        for meta in pays["metas"].values():
            assert (dist / base / meta["thumb"]).exists()
            assert (dist / base / meta["full"]).exists()


def test_la_meta_ne_porte_plus_le_chemin_source_apres_le_build(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    pays = json.loads(
        (dist / "data" / manifeste["countries"]["PL"]["file"]).read_text("utf-8")
    )
    assert "image_source" not in pays["metas"]["pl1"]


def test_image_base_est_dans_le_manifeste(projet):
    """La parade au plafond de fichiers : déplacer les images ne touche que ça."""
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert _manifeste(dist)["image_base"] == "img/"


def test_les_gabarits_recoivent_les_noms_empreintes(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    page = (dist / "index.html").read_text("utf-8")
    assert "__CSS__" not in page and "__JS__" not in page
    assert "style." in page and ".css" in page


def test_le_fichier_headers_est_produit_avec_les_deux_regimes(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    headers = (dist / "_headers").read_text("utf-8")
    assert "/data/manifest.json" in headers
    assert "no-cache" in headers
    assert "immutable" in headers


def test_deux_builds_identiques_donnent_les_memes_noms(projet):
    build_site(projet / "data", projet / "d1", projet / "viewer", ["PL"])
    build_site(projet / "data", projet / "d2", projet / "viewer", ["PL"])

    assert _manifeste(projet / "d1")["index"] == _manifeste(projet / "d2")["index"]


def test_skip_images_ne_produit_aucune_image(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"], skip_images=True)

    assert not (dist / "img").exists()


def test_le_resultat_compte_les_fichiers_produits(projet):
    resultat = build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    assert resultat["metas"] == 1
    assert resultat["files"] > 0
    assert FILE_COUNT_WARNING < FILE_COUNT_LIMIT


def test_une_image_source_absente_leve_avec_le_nom_de_la_meta(projet):
    (projet / "input" / "pl1.png").unlink()

    with pytest.raises(SystemExit, match="pl1"):
        build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])


def test_un_build_relance_ecrase_sans_laisser_de_residu(projet):
    dist = projet / "dist"
    build_site(projet / "data", dist, projet / "viewer", ["PL"])
    (dist / "data" / "vieux.json").write_text("{}", "utf-8")

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert not (dist / "data" / "vieux.json").exists()
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_build_site.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.build.site'`

- [ ] **Step 3: Écrire l'implémentation minimale**

Créer `cartometa/build/site.py` :

```python
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from cartometa.build.assets import write_hashed
from cartometa.build.dataset import build_dataset
from cartometa.build.geometry import DEFAULT_TOLERANCE
from cartometa.build.images import MissingImageError, render_image_pair

# Cloudflare Pages refuse un déploiement au-delà de 20 000 fichiers. On
# prévient bien avant pour que le mur soit vu venir des mois à l'avance : la
# parade (déplacer les images vers R2) demande une à deux heures, pas cinq
# minutes de panique.
FILE_COUNT_LIMIT = 20_000
FILE_COUNT_WARNING = 15_000

IMAGE_BASE = "img/"

HEADERS = """\
/index.html
  Cache-Control: no-cache
/licence.html
  Cache-Control: no-cache
/data/manifest.json
  Cache-Control: no-cache
/data/*
  Cache-Control: public, max-age=31536000, immutable
/img/*
  Cache-Control: public, max-age=31536000, immutable
/*.js
  Cache-Control: public, max-age=31536000, immutable
/*.css
  Cache-Control: public, max-age=31536000, immutable
"""


def _dumps(payload) -> bytes:
    """JSON compact et déterministe : sans espaces, clés triées.

    Le tri des clés est ce qui rend l'empreinte reproductible d'un build à
    l'autre — sans lui, l'ordre d'insertion suffirait à renouveler le nom du
    fichier et à vider le cache des visiteurs pour rien.
    """
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def build_site(
    data_dir: Path,
    out_dir: Path,
    viewer_dir: Path,
    countries: list[str],
    tolerance: float = DEFAULT_TOLERANCE,
    skip_images: bool = False,
    image_base: str = IMAGE_BASE,
) -> dict:
    """Produit un `dist/` complet et autonome.

    Table rase à chaque appel : un pays retiré des sources doit disparaître
    du site, pas survivre en fichier orphelin que le déploiement republierait.
    """
    jeu = build_dataset(data_dir, countries, tolerance)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    manifeste_pays: dict[str, dict] = {}
    for pays, contenu in sorted(jeu.countries.items()):
        for identifiant, meta in contenu["metas"].items():
            source = meta.pop("image_source", None)
            if skip_images or not source:
                continue
            try:
                noms = render_image_pair(
                    Path(source), out_dir / IMAGE_BASE / pays, identifiant
                )
            except MissingImageError as erreur:
                raise SystemExit(
                    f"{pays}/{identifiant} : {erreur}\n"
                    f"Les pages sources ne sont pas versionnées : vérifie input/."
                ) from erreur
            meta["thumb"] = f"{pays}/{noms['thumb']}"
            meta["full"] = f"{pays}/{noms['full']}"
        nom = write_hashed(out_dir / "data" / "c", pays, ".json", _dumps(contenu))
        manifeste_pays[pays] = {
            "file": f"c/{nom}", "count": len(contenu["geometries"])
        }

    nom_index = write_hashed(out_dir / "data", "index", ".json", _dumps(jeu.index))

    noms_statiques = {}
    for fichier, marqueur in (("style.css", "__CSS__"), ("app.js", "__JS__")):
        chemin = viewer_dir / fichier
        octets = chemin.read_bytes()
        tige, suffixe = chemin.stem, chemin.suffix
        noms_statiques[marqueur] = write_hashed(out_dir, tige, suffixe, octets)

    for page in ("index.html", "licence.html"):
        source = viewer_dir / page
        if not source.exists():
            continue
        texte = source.read_text("utf-8")
        for marqueur, nom in noms_statiques.items():
            texte = texte.replace(marqueur, nom)
        (out_dir / page).write_text(texte, "utf-8")

    (out_dir / "_headers").write_text(HEADERS, "utf-8")

    (out_dir / "data" / "manifest.json").write_text(json.dumps({
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta_count": len(jeu.index),
        # Lu par le front, jamais codé en dur : basculer les images vers un
        # bucket R2 se fait en changeant cette seule valeur.
        "image_base": image_base,
        "index": nom_index,
        "countries": manifeste_pays,
    }, ensure_ascii=False), "utf-8")

    fichiers = sum(1 for p in out_dir.rglob("*") if p.is_file())
    return {
        "metas": len(jeu.index),
        "countries": {p: e["count"] for p, e in manifeste_pays.items()},
        "files": fichiers,
        "legacy_statuses": jeu.legacy_statuses,
        "output": str(out_dir),
    }
```

Créer `cartometa/build/cli.py` :

```python
from __future__ import annotations

import argparse
from pathlib import Path

from cartometa.build.dataset import discover_countries
from cartometa.build.geometry import DEFAULT_TOLERANCE
from cartometa.build.site import (
    FILE_COUNT_LIMIT,
    FILE_COUNT_WARNING,
    IMAGE_BASE,
    build_site,
)


def main() -> None:
    analyseur = argparse.ArgumentParser(description="Construit le site public")
    analyseur.add_argument(
        "countries", nargs="*",
        help="Codes ISO à publier. Par défaut, tous ceux présents dans data/geo/.",
    )
    analyseur.add_argument("--data", type=Path, default=Path("data"))
    analyseur.add_argument("--out", type=Path, default=Path("dist"))
    analyseur.add_argument("--viewer", type=Path, default=Path("viewer"))
    analyseur.add_argument(
        "--simplify-tolerance", type=float, default=DEFAULT_TOLERANCE,
        help=f"Tolérance en degrés, plafonnée par emprise (défaut {DEFAULT_TOLERANCE}).",
    )
    analyseur.add_argument(
        "--skip-images", action="store_true",
        help="Saute l'encodage des images — pour itérer vite sur le code.",
    )
    analyseur.add_argument(
        "--image-base", default=IMAGE_BASE,
        help=(
            "Préfixe des URL d'images dans le manifeste. Passer une URL absolue "
            "(bucket R2 sur domaine personnalisé) déplace les images hors du "
            f"déploiement sans toucher au code. Défaut : {IMAGE_BASE}"
        ),
    )
    arguments = analyseur.parse_args()

    pays = [c.upper() for c in arguments.countries] or discover_countries(arguments.data)
    if not pays:
        raise SystemExit(
            f"Aucun pays à publier : {arguments.data / 'geo'} ne contient aucun "
            f".geojson.\nLance d'abord cartometa-extract puis cartometa-review."
        )

    resultat = build_site(
        arguments.data, arguments.out, arguments.viewer, pays,
        arguments.simplify_tolerance, arguments.skip_images,
        arguments.image_base,
    )

    detail = ", ".join(f"{p} {n}" for p, n in resultat["countries"].items())
    print(f"{resultat['metas']} métas publiées vers {resultat['output']} ({detail})")
    print(f"{resultat['files']} fichiers")

    if resultat["files"] >= FILE_COUNT_WARNING:
        print(
            f"\nAttention : {resultat['files']} fichiers, pour une limite de "
            f"{FILE_COUNT_LIMIT} par déploiement Cloudflare Pages.\n"
            f"Au plafond, c'est la publication qui échoue, pas le site en ligne.\n"
            f"Parade : déplacer img/ vers un bucket R2 et changer `image_base` "
            f"dans le manifeste."
        )
    if resultat["legacy_statuses"]:
        print(
            f"\nAttention : {resultat['legacy_statuses']} emprise(s) portent un "
            f"statut hérité (ni validé ni rejeté) et n'ont pas été publiées."
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Remplacer le script dans `pyproject.toml`**

Dans `[project.scripts]`, remplacer la ligne `cartometa-export` par :

```toml
cartometa-build = "cartometa.build.cli:main"
```

Puis supprimer l'ancien export et son test :

```bash
git rm cartometa/geo/export.py tests/test_export.py
uv sync
```

- [ ] **Step 5: Lancer toute la suite**

Run: `uv run pytest -q`
Expected: PASS, aucun échec, aucune référence résiduelle à `cartometa.geo.export`

- [ ] **Step 6: Commit**

```bash
git add cartometa/build/site.py cartometa/build/cli.py tests/test_build_site.py pyproject.toml
git commit -m "feat: commande cartometa-build, manifeste et en-tetes de cache"
```

---

### Task 6: Interface — structure, carte et chargement paresseux

**Files:**
- Modify: `viewer/index.html` (réécriture complète)
- Modify: `viewer/style.css` (réécriture complète)
- Modify: `viewer/app.js` (réécriture complète)

**Interfaces:**
- Consumes: le `dist/` de la tâche 5 — `data/manifest.json`, l'index global `[id, pays, minLon, minLat, maxLon, maxLat, surface]`, et les fichiers pays `{metas, geometries}`.
- Produces: la page servie. Les marqueurs `__CSS__` et `__JS__` dans les gabarits HTML sont remplacés au build.

- [ ] **Step 1: Réécrire `viewer/index.html`**

```html
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cartometa — les métas GeoGuessr par emprise</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <script defer src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <link rel="stylesheet" href="__CSS__">
  <script defer type="module" src="__JS__"></script>
</head>
<body>
  <header id="entete">
    <div class="marque">
      <span class="nom">Cartometa</span>
      <span class="baseline">les métas GeoGuessr, par emprise</span>
    </div>
    <span id="compteurs" class="compteurs"></span>
  </header>

  <main id="principal">
    <div id="carte"></div>
    <section id="panneau">
      <div id="filtres" hidden>
        <button class="pastille active" data-categorie="">Tout</button>
        <button class="pastille" data-categorie="poteaux">Poteaux</button>
        <button class="pastille" data-categorie="bollards">Bollards</button>
        <button class="pastille" data-categorie="signalisation">Signalisation</button>
        <button class="pastille" data-categorie="vegetation">Végétation</button>
        <button class="pastille" data-categorie="vehicule">Véhicule</button>
        <button class="pastille" data-categorie="autre">Autre</button>
        <input id="recherche" type="search" placeholder="Filtrer ces résultats…">
      </div>
      <div id="accueil">
        <h1>Cliquez n'importe où sur la carte</h1>
        <p>
          Vous verrez toutes les métas qui couvrent ce point, de la plus
          précise à la plus générale.
        </p>
      </div>
      <div id="galerie"></div>
    </section>
  </main>

  <footer id="pied">
    Textes et images © 2021-2026 Plonk It, CC BY-NC-SA 4.0 ·
    Imagery © Google · Fond © OpenStreetMap ·
    <a href="licence.html">licence et attribution</a>
  </footer>

  <div id="loupe" hidden>
    <button id="loupe-fermer" aria-label="Fermer">×</button>
    <img id="loupe-image" alt="">
    <p id="loupe-texte"></p>
  </div>
</body>
</html>
```

- [ ] **Step 2: Réécrire `viewer/style.css`**

```css
:root {
  --fond: #fbfbfa;
  --fond-carte: #ffffff;
  --trait: #e7e7e3;
  --texte: #1c1c1a;
  --texte-doux: #86867f;
  --accent: #c1283a;
  --rayon: 6px;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--fond);
  color: var(--texte);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}

#entete {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--trait);
  background: var(--fond-carte);
}
.marque { display: flex; align-items: baseline; gap: 10px; }
.nom { font-size: 16px; font-weight: 600; letter-spacing: -0.02em; }
.baseline, .compteurs { font-size: 11.5px; color: var(--texte-doux); }

#principal { flex: 1; display: flex; min-height: 0; }
#carte { flex: 0 0 46%; }
#panneau {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--trait);
  background: var(--fond-carte);
}

#filtres {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  padding: 10px 16px;
  border-bottom: 1px solid var(--trait);
}
.pastille {
  font: inherit;
  font-size: 11px;
  padding: 4px 11px;
  border: 1px solid var(--trait);
  border-radius: 99px;
  background: var(--fond-carte);
  color: var(--texte-doux);
  cursor: pointer;
}
.pastille.active { background: var(--texte); color: var(--fond-carte); border-color: var(--texte); }
#recherche {
  flex: 1;
  min-width: 140px;
  font: inherit;
  font-size: 11.5px;
  padding: 4px 10px;
  border: 1px solid var(--trait);
  border-radius: var(--rayon);
}

#accueil { padding: 28px 20px; max-width: 44ch; }
#accueil h1 { font-size: 17px; font-weight: 600; margin: 0 0 8px; }
#accueil p { margin: 0; color: var(--texte-doux); }

#galerie {
  flex: 1;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
  padding: 14px 16px;
  align-content: start;
}
#galerie:empty { padding: 0; }

.carte-meta { cursor: zoom-in; }
.carte-meta img {
  width: 100%;
  aspect-ratio: 16 / 8;
  object-fit: cover;
  border-radius: var(--rayon);
  display: block;
  background: #eeeeeb;
}
.carte-meta p {
  margin: 6px 0 0;
  font-size: 11.5px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.code-pays {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.07em;
  padding: 2px 5px;
  border-radius: 3px;
  background: var(--texte);
  color: var(--fond-carte);
  margin-right: 5px;
}

.squelette {
  aspect-ratio: 16 / 8;
  border-radius: var(--rayon);
  background: linear-gradient(90deg, #efefec 25%, #f7f7f4 50%, #efefec 75%);
  background-size: 200% 100%;
  animation: glisse 1.2s infinite;
}
@keyframes glisse { from { background-position: 200% 0; } to { background-position: -200% 0; } }

#vide { padding: 24px 20px; color: var(--texte-doux); grid-column: 1 / -1; }

#pied {
  padding: 7px 18px;
  border-top: 1px solid var(--trait);
  background: var(--fond-carte);
  font-size: 10.5px;
  color: var(--texte-doux);
}
#pied a { color: inherit; }

#loupe {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(20, 20, 18, 0.88);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 32px;
}
#loupe[hidden] { display: none; }
#loupe img { max-width: 100%; max-height: 76vh; object-fit: contain; border-radius: var(--rayon); }
#loupe p { color: #f2f2ee; max-width: 80ch; text-align: center; margin: 0; font-size: 13px; }
#loupe p a { color: #f2f2ee; }
#loupe-fermer {
  position: absolute;
  top: 16px;
  right: 20px;
  font-size: 26px;
  line-height: 1;
  background: none;
  border: none;
  color: #f2f2ee;
  cursor: pointer;
}
```

- [ ] **Step 3: Réécrire `viewer/app.js` — manifeste, index, carte, chargement paresseux**

```js
const etat = {
  manifeste: null,
  index: [],
  pays: new Map(),   // code pays -> {metas, geometries}
  resultats: [],
  categorie: '',
  recherche: '',
};

const carte = L.map('carte', { worldCopyJump: true }).setView([25, 15], 3);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 18,
}).addTo(carte);
const surlignage = L.layerGroup().addTo(carte);

async function demarrer() {
  const manifeste = await (await fetch('data/manifest.json')).json();
  etat.manifeste = manifeste;
  etat.index = await (await fetch(`data/${manifeste.index}`)).json();
  document.getElementById('compteurs').textContent =
    `${manifeste.meta_count} métas · ${Object.keys(manifeste.countries).length} pays`;
  restaurerVue();
}

// Un pays n'est téléchargé qu'une fois, et la promesse est mémorisée : deux
// clics rapides dans le même pays ne déclenchent pas deux requêtes.
const enCours = new Map();
function chargerPays(code) {
  if (etat.pays.has(code)) return Promise.resolve(etat.pays.get(code));
  if (enCours.has(code)) return enCours.get(code);
  const entree = etat.manifeste.countries[code];
  const promesse = fetch(`data/${entree.file}`)
    .then((r) => r.json())
    .then((contenu) => {
      etat.pays.set(code, contenu);
      enCours.delete(code);
      return contenu;
    });
  enCours.set(code, promesse);
  return promesse;
}

function dansAnneau(lon, lat, anneau) {
  let dedans = false;
  for (let i = 0, j = anneau.length - 1; i < anneau.length; j = i++) {
    const [xi, yi] = anneau[i];
    const [xj, yj] = anneau[j];
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      dedans = !dedans;
    }
  }
  return dedans;
}

function dansPolygone(lon, lat, anneaux) {
  if (!dansAnneau(lon, lat, anneaux[0])) return false;
  for (let i = 1; i < anneaux.length; i += 1) {
    if (dansAnneau(lon, lat, anneaux[i])) return false; // trou
  }
  return true;
}

function contient(geometrie, lon, lat) {
  if (geometrie.type === 'Polygon') return dansPolygone(lon, lat, geometrie.coordinates);
  return geometrie.coordinates.some((anneaux) => dansPolygone(lon, lat, anneaux));
}

async function interroger(lon, lat) {
  // L'index est déjà trié par surface croissante : l'ordre du résultat est
  // celui du plus spécifique au plus général, sans retrier.
  const candidats = etat.index.filter(([, , minLon, minLat, maxLon, maxLat]) =>
    lon >= minLon && lon <= maxLon && lat >= minLat && lat <= maxLat);
  const codes = [...new Set(candidats.map(([, code]) => code))];
  await Promise.all(codes.map(chargerPays));
  return candidats
    .filter(([id, code]) => contient(etat.pays.get(code).geometries[id], lon, lat))
    .map(([id, code]) => ({ id, code, ...etat.pays.get(code).metas[id] }));
}

carte.on('click', async (evenement) => {
  const { lng: lon, lat } = evenement.latlng;
  document.getElementById('accueil').hidden = true;
  document.getElementById('filtres').hidden = false;
  afficherSquelettes();
  surlignage.clearLayers();
  etat.resultats = await interroger(lon, lat);
  rendre();
  memoriserVue();
});

function memoriserVue() {
  const centre = carte.getCenter();
  history.replaceState(null, '',
    `#${centre.lat.toFixed(4)},${centre.lng.toFixed(4)},${carte.getZoom()}`);
}

function restaurerVue() {
  const [lat, lon, zoom] = location.hash.slice(1).split(',').map(Number);
  if ([lat, lon, zoom].every(Number.isFinite)) carte.setView([lat, lon], zoom);
}

carte.on('moveend', memoriserVue);
demarrer();
```

Les fonctions `afficherSquelettes` et `rendre` sont écrites en tâche 7. Pour que cette tâche soit testable seule, ajouter provisoirement à la fin du fichier :

```js
function afficherSquelettes() {}
function rendre() { console.debug(etat.resultats.length, 'résultats'); }
```

- [ ] **Step 4: Vérifier à l'écran**

```bash
uv run cartometa-build PL BW
python -m http.server 8010 --directory dist
```

Ouvrir <http://127.0.0.1:8010/>. Attendu :
- l'en-tête affiche le nombre de métas et de pays ;
- l'onglet réseau montre `manifest.json` puis `index.<hash>.json`, **et rien d'autre** avant le premier clic ;
- un clic dans une emprise déclenche le téléchargement d'un seul `c/<CC>.<hash>.json` ;
- la console affiche le nombre de résultats ;
- un second clic dans le même pays ne relance aucune requête ;
- l'URL porte `#lat,lon,zoom` et un rechargement restaure la vue.

- [ ] **Step 5: Commit**

```bash
git add viewer/index.html viewer/style.css viewer/app.js
git commit -m "feat: interface carte-galerie et chargement paresseux par pays"
```

---

### Task 7: Interface — galerie, filtres et agrandissement

**Files:**
- Modify: `viewer/app.js` (remplacer les deux fonctions provisoires de la tâche 6)

**Interfaces:**
- Consumes: `etat`, `surlignage`, `carte` (tâche 6) ; `manifeste.image_base` pour composer les URL d'images.
- Produces: `rendre()`, `afficherSquelettes()`, `visibles()`, `ouvrirLoupe(meta)`.

- [ ] **Step 1: Remplacer les fonctions provisoires**

Supprimer les deux stubs de la tâche 6 et ajouter, à leur place :

```js
const galerie = document.getElementById('galerie');
const loupe = document.getElementById('loupe');

function urlImage(nom) {
  return etat.manifeste.image_base + nom;
}

function afficherSquelettes() {
  galerie.innerHTML = '<div class="squelette"></div>'.repeat(4);
}

function visibles() {
  const terme = etat.recherche.trim().toLowerCase();
  return etat.resultats.filter((meta) => {
    if (etat.categorie && meta.category !== etat.categorie) return false;
    if (!terme) return true;
    return `${meta.title} ${meta.description}`.toLowerCase().includes(terme);
  });
}

function rendre() {
  const metas = visibles();
  galerie.innerHTML = '';
  if (!metas.length) {
    const vide = document.createElement('p');
    vide.id = 'vide';
    vide.textContent = etat.resultats.length
      ? 'Aucune méta ne correspond à ce filtre.'
      : 'Aucune méta ne couvre ce point.';
    galerie.appendChild(vide);
    return;
  }
  for (const meta of metas) {
    const bloc = document.createElement('article');
    bloc.className = 'carte-meta';
    // textContent plutôt qu'innerHTML : les titres viennent d'un HTML tiers
    // et peuvent contenir n'importe quoi.
    const image = document.createElement('img');
    image.loading = 'lazy';
    image.src = urlImage(meta.thumb);
    image.alt = '';
    const legende = document.createElement('p');
    const code = document.createElement('span');
    code.className = 'code-pays';
    code.textContent = meta.code;
    legende.append(code, document.createTextNode(meta.title));
    bloc.append(image, legende);
    bloc.addEventListener('mouseenter', () => {
      surlignage.clearLayers();
      L.geoJSON(etat.pays.get(meta.code).geometries[meta.id], {
        color: 'var(--accent)', weight: 2, fillOpacity: 0.18,
      }).addTo(surlignage);
    });
    bloc.addEventListener('click', () => ouvrirLoupe(meta));
    galerie.appendChild(bloc);
  }
}

function ouvrirLoupe(meta) {
  document.getElementById('loupe-image').src = urlImage(meta.full);
  const texte = document.getElementById('loupe-texte');
  texte.textContent = `${meta.title} `;
  const lien = document.createElement('a');
  lien.href = meta.source_url;
  lien.target = '_blank';
  lien.rel = 'noopener';
  lien.textContent = 'source';
  texte.appendChild(lien);
  loupe.hidden = false;
}

function fermerLoupe() {
  loupe.hidden = true;
  document.getElementById('loupe-image').src = '';
}

document.getElementById('loupe-fermer').addEventListener('click', fermerLoupe);
loupe.addEventListener('click', (e) => { if (e.target === loupe) fermerLoupe(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') fermerLoupe(); });

document.getElementById('recherche').addEventListener('input', (e) => {
  etat.recherche = e.target.value;
  rendre();
});

for (const pastille of document.querySelectorAll('.pastille')) {
  pastille.addEventListener('click', () => {
    for (const autre of document.querySelectorAll('.pastille')) {
      autre.classList.toggle('active', autre === pastille);
    }
    etat.categorie = pastille.dataset.categorie;
    rendre();
  });
}
```

- [ ] **Step 2: Vérifier à l'écran**

```bash
uv run cartometa-build
python -m http.server 8010 --directory dist
```

Liste de contrôle sur <http://127.0.0.1:8010/> :
- l'accueil affiche le texte d'invitation, la galerie est vide ;
- un clic dans une emprise affiche d'abord quatre cases grises animées, puis les vignettes ;
- les vignettes sont ordonnées de la plus petite emprise à la plus grande ;
- survoler une vignette surligne son emprise en rouge sur la carte ;
- cliquer une vignette ouvre l'image pleine taille, avec le titre complet et le lien « source » ;
- `Échap`, la croix et un clic sur le fond ferment l'agrandissement ;
- les pastilles de catégorie et le champ de recherche filtrent les résultats du clic courant ;
- un clic en pleine mer affiche « Aucune méta ne couvre ce point. » ;
- le pied de page affiche l'attribution complète.

- [ ] **Step 3: Commit**

```bash
git add viewer/app.js
git commit -m "feat: galerie, filtres, surlignage et agrandissement"
```

---

### Task 8: Licences, attribution et sortie de `viewer/data` du dépôt

**Files:**
- Create: `viewer/licence.html`
- Create: `LICENSE`
- Create: `LICENSE-DATA`
- Create: `CONTRIBUTING.md`
- Modify: `.gitignore`
- Modify: `README.md`
- Delete (du suivi git) : `viewer/data/index.json`, `viewer/data/geometries.json`
- Test: `tests/test_build_site.py` (ajout)

**Interfaces:**
- Consumes: `build_site` (tâche 5), qui copie `licence.html` en y substituant `__CSS__`.
- Produces: rien de programmatique.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/test_build_site.py` :

```python
def test_la_page_de_licence_est_publiee(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert (dist / "licence.html").exists()
```

Run: `uv run pytest tests/test_build_site.py::test_la_page_de_licence_est_publiee -v`
Expected: PASS déjà — la tâche 5 copie `licence.html` quand il existe. Le test verrouille ce comportement contre une régression.

- [ ] **Step 2: Créer `viewer/licence.html`**

```html
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cartometa — licence et attribution</title>
  <link rel="stylesheet" href="__CSS__">
  <style>
    body { display: block; }
    main { max-width: 68ch; margin: 0 auto; padding: 40px 24px 80px; }
    h1 { font-size: 22px; } h2 { font-size: 15px; margin-top: 32px; }
    p, li { color: #45453f; }
  </style>
</head>
<body>
  <main>
    <p><a href="index.html">← retour à la carte</a></p>
    <h1>Licence et attribution</h1>

    <h2>Ce qui vient de Plonk It</h2>
    <p>
      Les titres, descriptions et images des métas proviennent de
      <a href="https://www.plonkit.net" rel="noopener">Plonk It</a>,
      © 2021-2026 Plonk It, publiés sous licence
      <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/deed.fr" rel="noopener">
        Creative Commons Attribution - Pas d'Utilisation Commerciale -
        Partage dans les Mêmes Conditions 4.0 International</a>.
      Chaque méta porte un lien « source » vers sa page d'origine.
    </p>
    <p>
      <strong>Le matériel a été modifié</strong> : les textes ont été
      restructurés, et chaque méta s'est vu associer une emprise géographique
      qui n'existe pas dans la source.
    </p>

    <h2>Ce qui vient de ce projet</h2>
    <p>
      Les emprises géographiques sont tracées à la main, une par une. Elles
      sont publiées sous la même licence CC BY-NC-SA 4.0, partage à
      l'identique oblige. Le code du site est distribué séparément sous
      licence MIT.
    </p>

    <h2>Imagerie</h2>
    <p>
      Les captures de métas proviennent de Google Street View. La licence
      Creative Commons de Plonk It couvre leurs annotations et leur montage,
      pas l'imagerie sous-jacente, qui reste © Google. Les filigranes
      présents dans les images d'origine n'ont pas été retirés.
      Le fond de carte est © OpenStreetMap et ses contributeurs.
    </p>

    <h2>Usage non commercial</h2>
    <p>
      Ce site est un projet personnel sans publicité, sans sponsor et sans
      contrepartie financière d'aucune sorte.
    </p>

    <h2>Contact</h2>
    <p>
      Pour toute demande, y compris une demande de retrait :
      <a href="mailto:psmague@gmail.com">psmague@gmail.com</a>.
    </p>
  </main>
</body>
</html>
```

- [ ] **Step 3: Créer les fichiers de licence et de contribution**

`LICENSE` — texte intégral de la licence MIT, titulaire « Pierre Smague », année 2026, précédé de cette ligne :

```
Cette licence couvre le CODE de Cartometa. Les DONNÉES publiées (textes,
images et emprises) relèvent de LICENSE-DATA.
```

`LICENSE-DATA` :

```
Les données publiées par Cartometa — titres, descriptions et images des métas,
ainsi que les emprises géographiques tracées pour ce projet — sont distribuées
sous licence Creative Commons Attribution - Pas d'Utilisation Commerciale -
Partage dans les Mêmes Conditions 4.0 International (CC BY-NC-SA 4.0).

https://creativecommons.org/licenses/by-nc-sa/4.0/deed.fr

Les textes et images sont © 2021-2026 Plonk It (https://www.plonkit.net) et
repris sous cette même licence. Ils ont été modifiés : restructurés, et
associés à des emprises géographiques absentes de la source.

L'imagerie Street View sous-jacente reste © Google et n'est couverte ni par
la licence de Plonk It ni par la présente.

Contact : psmague@gmail.com
```

`CONTRIBUTING.md` :

```markdown
# Contribuer à Cartometa

Les contributions portent aujourd'hui sur le tracé des emprises. Le circuit
est celui de la pull request : installe l'outil, trace, propose.

## Licence des contributions

En proposant une contribution, tu acceptes qu'elle soit publiée sous
**CC BY-NC-SA 4.0**, comme le reste des données du projet. C'est une
obligation de la licence de la source, pas un choix : Plonk It publie sous
partage à l'identique.

Le code, lui, reste sous licence MIT.

## Circuit

1. `uv sync`
2. `uv run cartometa-extract <pays>` — la page source se capture à la main,
   voir le README. **Ne jamais écrire de crawler pour plonkit.net.**
3. `uv run cartometa-review <CC>` — trace les emprises.
4. Propose une pull request avec le `data/geo/<CC>.geojson` modifié.

La publication du site est faite séparément par le mainteneur.
```

- [ ] **Step 4: Sortir `viewer/data/` du suivi git**

Ajouter à `.gitignore` :

```
# Artefact de build du site public
dist/
# Données du viewer : régénérées par cartometa-build, jamais versionnées
viewer/data/
```

Puis :

```bash
git rm --cached viewer/data/index.json viewer/data/geometries.json
```

- [ ] **Step 5: Mettre à jour le README**

Remplacer la section « Consulter la carte » et l'étape 4 « Publier vers le viewer » par :

````markdown
## Consulter la carte

```
uv run cartometa-build
python -m http.server 8010 --directory dist
```

puis <http://127.0.0.1:8010/>. `Ctrl+C` pour arrêter.

Clic sur la carte → galerie des métas triées par surface croissante. Survol
d'une vignette → son emprise sur la carte. Clic → image pleine taille.

### 4. Publier

```
uv run cartometa-build
npx wrangler pages deploy dist --project-name cartometa
```

`cartometa-build` produit un `dist/` autonome et gitignoré : géométries
simplifiées et découpées par pays, images en deux tailles, empreintes de
contenu pour le cache. Les images sources vivant dans `input/`, non versionné,
le site ne peut être construit que localement.

Options utiles : `--skip-images` pour itérer vite sur le code,
`--simplify-tolerance` pour ajuster la finesse des contours (défaut 0,01°,
plafonnée par la taille de chaque emprise).
````

- [ ] **Step 6: Lancer toute la suite et construire pour de vrai**

```bash
uv run pytest -q
uv run cartometa-build
git status
```

Attendu : tous les tests passent ; le build affiche le nombre de métas, de pays et de fichiers ; `git status` ne montre **ni** `dist/` **ni** `viewer/data/`.

- [ ] **Step 7: Commit**

```bash
git add LICENSE LICENSE-DATA CONTRIBUTING.md viewer/licence.html .gitignore README.md tests/test_build_site.py
git commit -m "docs: licences, attribution et sortie de viewer/data du depot"
```

---

## Auto-relecture

**Couverture de la spec.**

| Section de la spec | Tâche |
|---|---|
| §3.1 source / artefact | 5 (table rase), 8 (gitignore) |
| §3.2 arborescence | 5 |
| §3.3 commande de build | 5 |
| §4.1 manifeste | 5 |
| §4.2 index global | 2 |
| §4.3 fichier par pays | 2, 5 |
| §5 chargement et requête | 6 |
| §6 simplification | 1 |
| §7 images | 4 |
| §8 cache | 5 |
| §9 mise à l'échelle | 5 (avertissement à 15 000) |
| §10 interface | 6, 7 |
| §11 attribution | 7 (pied), 8 (pages et fichiers) |
| §12 tests | 1 à 5, 8 |
| §13 périmètre | respecté — aucune tâche mobile, aucune recherche globale |
| §14 critères | vérifiés en tâches 5 à 8 |

Aucune section sans tâche.

**Écarts assumés et signalés.**

- Les vérifications de simplification de la §6 (Hausdorff, écart de surface) sont implémentées comme **fonctions de mesure testées** (`hausdorff`, `area_ratio`) plutôt que comme un garde-fou levant à chaque build : sur 1679 emprises, une exception bloquerait la publication pour un cas limite. Le repli sur l'original arrondi, lui, est dans le code.
- Les tâches 6 et 7 n'ont pas de test automatisé : le dépôt n'a pas d'infrastructure JS et ce plan n'en crée pas. Elles ont chacune une liste de contrôle manuelle explicite.

**Cohérence des noms.** `simplify_geometry`, `build_dataset`, `write_hashed`, `render_image_pair`, `build_site` sont employés partout sous la même signature. `image_source` est produit en tâche 2 et retiré en tâche 5 ; `thumb` et `full` le remplacent, et sont consommés en tâche 7. Les marqueurs `__CSS__` et `__JS__` sont posés en tâche 6, substitués en tâche 5, et réutilisés dans `licence.html` en tâche 8.
