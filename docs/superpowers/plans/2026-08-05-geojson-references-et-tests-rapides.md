# GeoJSON par références + tests rapides — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ne plus stocker dans `data/geo/*.geojson` les géométries reconstructibles depuis les `pieces` (silhouettes pays et régions Natural Earth), et ramener la suite de tests de 33 min à ~1 min sur données inchangées.

**Architecture:** Les `pieces` sont déjà la source de vérité (`GeoRecord` docstring : « the geometry alone cannot be decomposed »). `save_geo` cesse d'écrire la géométrie quand toutes les pièces sont des références (`country`/`admin1`/`clip`) ; `load_geo` gagne un paramètre `resolve` qui la reconstruit via `resolve_pieces` pour les consommateurs qui en ont besoin (build du site, tests real_data). Le serveur de revue n'a jamais besoin de la géométrie stockée (le client reconstruit depuis les pièces). Les tests real_data dédupliquent les géométries par hash et mémorisent les vérifications réussies dans `data/cache/` (gitignoré).

**Tech Stack:** Python 3, shapely, pytest. Venv Windows : `.venv/Scripts/python.exe`.

## Global Constraints

- Lancer les tests avec `.venv/Scripts/python.exe -m pytest` depuis la racine du repo.
- Messages de commit en français ASCII (sans accents), terminés par `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Style : suivre le style du fichier touché (docstrings en anglais dans `cartometa/`, identifiants français tolérés comme `_arrondi_coords`).
- TDD strict : test écrit et vu échouer avant chaque implémentation.
- Ne jamais committer `data/cache/`, `data/metas/`, `input/` (gitignorés).
- La suite complète actuelle : 361 tests, ~33 min. Ne rien casser : chaque tâche laisse la suite hors `real_data` verte (`-m "not real_data"`, ~50 s au départ, ~21 s après la tâche 1).

## Contexte mesuré (2026-08-05)

- `data/geo` : 183 Mo. CA.geojson 37 Mo (28 Mo redondants), US.geojson 33 Mo (27 Mo redondants). Aux US, 37 métas « pays » stockent chacune la silhouette nationale de 772 Ko ; leurs `pieces` valent toutes `[{"kind": "country"}]`.
- Suite de tests : 50 s hors `real_data` (dont 29 s pour un seul test qui compresse 10,8 Go de zéros), ~32 min pour les 5 tests de `tests/test_real_data.py`, dominées par `hausdorff()` (46 s par grosse géométrie côtière, appelé pour chaque copie dupliquée).

---

### Task 1: Branche + PNG de bombe rapide

**Files:**
- Modify: `tests/test_manual_meta.py:42`

**Interfaces:**
- Produces: rien pour les autres tâches ; gain de 28 s sur la suite rapide.

- [ ] **Step 1: Créer la branche**

```bash
git checkout master && git pull && git checkout -b perf/geojson-references-et-tests-rapides
```

(Si `master` a divergé à cause de la PR #8 non mergée, partir de `master` quand même : ce chantier est indépendant du fix du parseur.)

- [ ] **Step 2: Mesurer le test avant modification**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manual_meta.py::test_a_decompression_bomb_is_refused --durations=1 -q`
Expected: PASS, durée ~29 s affichée par `--durations`.

- [ ] **Step 3: Remplacer la fabrication de l'IDAT**

Dans `tests/test_manual_meta.py`, fonction `_decompression_bomb_png`, remplacer :

```python
    compressed = zlib.compress(b'\x00' * (width * height * 3))[:100]
```

par :

```python
    # PIL rejette la bombe des l'en-tete IHDR (60000x60000 pixels declares),
    # sans jamais decoder l'IDAT : inutile de compresser 10,8 Go de zeros
    # reels, 1 Ko donne le meme DecompressionBombError en 30 ms au lieu de 29 s.
    compressed = zlib.compress(b'\x00' * 1024)[:100]
```

- [ ] **Step 4: Vérifier que le test passe toujours, vite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manual_meta.py --durations=3 -q`
Expected: tous PASS, `test_a_decompression_bomb_is_refused` sous la seconde.

- [ ] **Step 5: Commit**

```bash
git add tests/test_manual_meta.py
git commit -m "perf(tests): la bombe PNG n'a plus besoin de compresser 10 Go de zeros

PIL rejette sur les dimensions declarees dans l'IHDR sans decoder
l'IDAT : 1 Ko de donnees suffit. 29 s -> moins d'une seconde, sur une
suite rapide qui en faisait 50.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Mémoïser les silhouettes Natural Earth

**Files:**
- Modify: `cartometa/geo/reference.py:92` (`country_geometry`)
- Modify: `cartometa/geo/admin1.py:73` (`region_geometry`)
- Test: `tests/test_reference.py`, `tests/test_admin1.py`

**Interfaces:**
- Consumes: rien.
- Produces: `country_geometry(iso_a2: str, cache_dir: Path) -> BaseGeometry` et `region_geometry(iso_a2: str, code: str, cache_dir: Path) -> BaseGeometry`, signatures inchangées mais mémoïsées — la tâche 3 les appellera via `resolve_pieces` une fois par méta sans repayer le `shape()` d'une silhouette de 1,4 Mo à chaque appel.

- [ ] **Step 1: Écrire les tests qui échouent**

Dans `tests/test_reference.py`, ajouter (reprendre la fixture existante du fichier qui fabrique un faux `ne_10m_admin_0_countries.geojson` dans un tmp_path ; si elle porte un autre nom, adapter l'argument) :

```python
def test_country_geometry_is_memoized(cache_dir):
    """Two calls for the same country must not rebuild the shapely geometry:
    resolve_pieces will ask for the national silhouette once per country-tier
    meta (37 times for the US)."""
    assert country_geometry("PL", cache_dir) is country_geometry("PL", cache_dir)
```

Dans `tests/test_admin1.py`, ajouter l'équivalent :

```python
def test_region_geometry_is_memoized(cache_dir):
    assert (
        region_geometry("PL", "POL-1", cache_dir)
        is region_geometry("PL", "POL-1", cache_dir)
    )
```

Avant d'écrire, lire les fixtures existantes de ces deux fichiers de test et réutiliser leur manière de fabriquer le faux référentiel (même motif que `tests/test_pieces.py` : `(tmp_path / DATASET_NAME).write_text(...)` et `(tmp_path / "admin1" / "PL.geojson")`).

- [ ] **Step 2: Les voir échouer**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reference.py tests/test_admin1.py -q -k memoized`
Expected: 2 FAILED sur l'assertion `is` (deux objets shapely distincts).

- [ ] **Step 3: Mémoïser**

Dans `cartometa/geo/reference.py`, décorer `country_geometry` :

```python
@lru_cache(maxsize=64)
def country_geometry(iso_a2: str, cache_dir: Path) -> BaseGeometry:
```

(`lru_cache` est déjà importé dans ce fichier. `Path` est hashable ; les tests qui utilisent des tmp_path distincts ont donc des clés distinctes.)

Dans `cartometa/geo/admin1.py`, décorer `region_geometry` :

```python
@lru_cache(maxsize=512)
def region_geometry(iso_a2: str, code: str, cache_dir: Path) -> BaseGeometry:
```

Ajouter au docstring de chacun une ligne : `Memoized: callers must treat the returned geometry as immutable.` Les opérations shapely (union, intersection) ne mutent pas leurs entrées — c'est le contrat de tous les appels existants.

- [ ] **Step 4: Vérifier**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reference.py tests/test_admin1.py tests/test_pieces.py -q`
Expected: tous PASS. Si un test existant échoue parce qu'il comptait les lectures de fichiers après un premier appel, adapter CE test (le comportement mémoïsé est le comportement voulu), en le notant dans le message de commit.

- [ ] **Step 5: Commit**

```bash
git add cartometa/geo/reference.py cartometa/geo/admin1.py tests/test_reference.py tests/test_admin1.py
git commit -m "perf: memoiser les silhouettes Natural Earth

resolve_pieces redemande la meme silhouette pour chaque meta pays (37
fois pour les US) : le shape() d'un trait de cote de 1,4 Mo ne doit se
payer qu'une fois par processus.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `save_geo` élague les géométries de référence, `load_geo` sait les résoudre

**Files:**
- Modify: `cartometa/review/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `resolve_pieces(pieces, country, cache_dir)` de `cartometa.review.pieces` (existant), `country_geometry`/`region_geometry` mémoïsés (tâche 2).
- Produces: `load_geo(paths: CountryPaths, resolve: bool = False) -> dict[str, GeoRecord]`. Avec `resolve=True`, tout `GeoRecord` de statut `validé` à géométrie `None` et pièces non vides ressort avec sa géométrie reconstruite (dict GeoJSON en listes pures). `save_geo` écrit `geometry: null` quand toutes les pièces sont dans `REFERENCE_KINDS = {"country", "admin1", "clip"}`. Constante exportée : `REFERENCE_KINDS`.

- [ ] **Step 1: Écrire les tests qui échouent**

Dans `tests/test_store.py`, ajouter. Lire d'abord les fixtures existantes du fichier (il teste déjà `save_geo`/`load_geo` avec un `CountryPaths(tmp_path, ...)`) et réutiliser leurs helpers. Le faux référentiel copie le motif de `tests/test_pieces.py` :

```python
from cartometa.geo.reference import DATASET_NAME
from cartometa.review.store import CountryPaths, load_geo, save_geo
from cartometa.models import GeoRecord

CARRE_PL = {"type": "Polygon",
            "coordinates": [[[14.0, 49.0], [24.0, 49.0], [24.0, 55.0],
                             [14.0, 55.0], [14.0, 49.0]]]}


def _paths_avec_reference(tmp_path):
    """CountryPaths dont data/cache contient un faux Natural Earth pour PL."""
    paths = CountryPaths(tmp_path, "PL")
    cache = paths.cache
    cache.mkdir(parents=True)
    (cache / DATASET_NAME).write_text(json.dumps({
        "type": "FeatureCollection", "features": [{
            "type": "Feature",
            "properties": {"ISO_A2": "PL", "ISO_A2_EH": "PL", "NAME": "Poland"},
            "geometry": CARRE_PL,
        }],
    }), "utf-8")
    return paths


def test_save_strips_the_geometry_when_every_piece_is_a_reference(tmp_path):
    paths = _paths_avec_reference(tmp_path)
    records = {"m1": GeoRecord(id="m1", geometry=dict(CARRE_PL),
                               pieces=[{"kind": "country"}])}

    save_geo(paths, records)

    feature = json.loads(paths.geo.read_text("utf-8"))["features"][0]
    assert feature["geometry"] is None
    assert feature["properties"]["pieces"] == [{"kind": "country"}]


def test_save_keeps_the_geometry_when_a_piece_is_hand_drawn(tmp_path):
    paths = _paths_avec_reference(tmp_path)
    triangle = {"type": "Polygon",
                "coordinates": [[[15.0, 50.0], [16.0, 50.0], [15.0, 51.0],
                                 [15.0, 50.0]]]}
    records = {"m1": GeoRecord(
        id="m1", geometry=triangle,
        pieces=[{"kind": "polygon",
                 "ring": [[15.0, 50.0], [16.0, 50.0], [15.0, 51.0]]},
                {"kind": "clip"}])}

    save_geo(paths, records)

    feature = json.loads(paths.geo.read_text("utf-8"))["features"][0]
    assert feature["geometry"] is not None


def test_load_without_resolve_leaves_stripped_geometry_none(tmp_path):
    paths = _paths_avec_reference(tmp_path)
    save_geo(paths, {"m1": GeoRecord(id="m1", geometry=dict(CARRE_PL),
                                     pieces=[{"kind": "country"}])})

    assert load_geo(paths)["m1"].geometry is None


def test_load_with_resolve_rebuilds_the_reference_geometry(tmp_path):
    paths = _paths_avec_reference(tmp_path)
    save_geo(paths, {"m1": GeoRecord(id="m1", geometry=dict(CARRE_PL),
                                     pieces=[{"kind": "country"}])})

    record = load_geo(paths, resolve=True)["m1"]

    assert record.geometry is not None
    from shapely.geometry import shape
    assert shape(record.geometry).equals(shape(CARRE_PL))


def test_load_with_resolve_ignores_rejected_metas(tmp_path):
    paths = _paths_avec_reference(tmp_path)
    save_geo(paths, {"m1": GeoRecord(id="m1", geometry=None, pieces=[],
                                     status="rejeté")})

    assert load_geo(paths, resolve=True)["m1"].geometry is None


def test_save_load_save_round_trip_is_byte_stable(tmp_path):
    paths = _paths_avec_reference(tmp_path)
    save_geo(paths, {"m1": GeoRecord(id="m1", geometry=dict(CARRE_PL),
                                     pieces=[{"kind": "country"}])})
    premier = paths.geo.read_bytes()

    save_geo(paths, load_geo(paths))

    assert paths.geo.read_bytes() == premier
```

- [ ] **Step 2: Les voir échouer**

Run: `.venv/Scripts/python.exe -m pytest tests/test_store.py -q -k "strip or resolve or round_trip"`
Expected: FAIL — `save_geo` écrit encore la géométrie (`assert feature["geometry"] is None` échoue), `load_geo` ne connaît pas `resolve` (TypeError).

- [ ] **Step 3: Implémenter dans `cartometa/review/store.py`**

Ajouter en tête (après les imports existants) :

```python
from shapely.geometry import mapping

from cartometa.review.pieces import resolve_pieces

# Piece kinds whose surface comes entirely from the Natural Earth reference:
# the resulting geometry is a pure cache, reconstructible at read time.
# "clip" brings no surface of its own (it intersects with the country outline,
# also reference data), so it does not anchor anything hand-drawn.
REFERENCE_KINDS = frozenset({"country", "admin1", "clip"})
```

Attention à l'import shapely existant ligne 7 : le compléter (`from shapely.geometry import Polygon, mapping, shape`).

Ajouter le prédicat et la résolution :

```python
def _geometry_is_derivable(record: GeoRecord) -> bool:
    """True when the stored geometry is a pure cache of the reference data.

    The pieces are the human decision (cf. GeoRecord docstring); when every
    piece is a reference descriptor, the geometry was itself produced by
    resolve_pieces at decision time and weighs megabytes for nothing: the US
    file stored 37 copies of the 772 KB national silhouette.
    """
    return bool(record.pieces) and all(
        piece.get("kind") in REFERENCE_KINDS for piece in record.pieces
    )


def _resolved_geometry(record: GeoRecord, paths: CountryPaths) -> dict:
    resolved = resolve_pieces(record.pieces, paths.country, paths.cache)
    # json round-trip: mapping() yields tuples, consumers and the byte-stable
    # round-trip expect plain lists.
    return json.loads(json.dumps(mapping(resolved)))
```

Remplacer `load_geo` :

```python
def load_geo(paths: CountryPaths, resolve: bool = False) -> dict[str, GeoRecord]:
    """The country's decisions, keyed by meta id.

    `resolve=False` (default): stripped reference geometries stay None — enough
    for the review queue and for re-saving, which strips them again anyway.
    `resolve=True`: rebuild them from the pieces via Natural Earth; needed by
    the site build and the real-data tests. May download the reference dataset
    into `paths.cache` on a fresh clone, exactly like the review server does.
    """
    if not paths.geo.exists():
        return {}
    data = json.loads(paths.geo.read_text("utf-8"))
    records = [GeoRecord.from_feature(f) for f in data.get("features", [])]
    if resolve:
        for record in records:
            if record.geometry is None and record.status == STATUS_TRACED and record.pieces:
                record.geometry = _resolved_geometry(record, paths)
    return {record.id: record for record in records}
```

(`STATUS_TRACED` s'importe depuis `cartometa.models`, à côté de `STATUSES` déjà importé.)

Dans `save_geo`, élaguer avant l'arrondi — remplacer la compréhension existante :

```python
        "features": [
            _feature_arrondie(records[key].to_feature()) for key in sorted(records)
        ],
```

par :

```python
        "features": [
            _feature_allegee(records[key]) for key in sorted(records)
        ],
```

et ajouter au-dessus de `save_geo` :

```python
def _feature_allegee(record: GeoRecord) -> dict:
    """The feature to store: rounded, and without its geometry when the pieces
    alone can rebuild it."""
    feature = _feature_arrondie(record.to_feature())
    if _geometry_is_derivable(record):
        feature["geometry"] = None
    return feature
```

- [ ] **Step 4: Vérifier**

Run: `.venv/Scripts/python.exe -m pytest tests/test_store.py tests/test_review_server.py tests/test_pieces.py -q`
Expected: tous PASS. Les tests existants de `test_store.py` (arrondi, statuts) utilisent des pièces `polygon` : ils ne doivent pas être affectés. Si un test existant sauvait des pièces pures références et relisait la géométrie, l'adapter à `resolve=True` en le notant dans le commit.

- [ ] **Step 5: Commit**

```bash
git add cartometa/review/store.py tests/test_store.py
git commit -m "feat: ne plus stocker les geometries reconstructibles des pieces

Les pieces sont la source de verite ; quand elles sont de pures
references (country/admin1/clip), la geometrie stockee n'est qu'un
cache de Natural Earth : 37 copies de la silhouette US, 28 des 30 Mo
du fichier. save_geo ecrit null, load_geo(resolve=True) reconstruit.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Le build du site lit via `load_geo(resolve=True)`

**Files:**
- Modify: `cartometa/build/dataset.py:139-145` (et les usages de `geo["features"]` plus bas dans la même fonction)
- Test: `tests/test_build_dataset.py`

**Interfaces:**
- Consumes: `load_geo(paths, resolve=True)` (tâche 3).
- Produces: le build produit exactement le même dataset qu'avant sur des fichiers élagués.

- [ ] **Step 1: Écrire le test qui échoue**

Dans `tests/test_build_dataset.py`, ajouter un test qui construit le dataset depuis un fichier geo ÉLAGUÉ (géométrie `null`, pièce `country`) plus un faux Natural Earth dans `data/cache`, et vérifie que la méta ressort avec une géométrie. Lire d'abord les fixtures existantes du fichier (elles fabriquent déjà `data/metas/XX.json` + `data/geo/XX.geojson` dans un tmp_path et appellent la fonction de build — réutiliser exactement le même échafaudage, seul le contenu du geojson change) :

```python
def test_a_stripped_reference_geometry_is_resolved_at_build_time(tmp_path):
    # même échafaudage que les tests voisins : metas + geo + cache dans tmp_path
    # geo: {"type": "Feature", "geometry": None,
    #       "properties": {"id": ..., "status": "validé",
    #                      "pieces": [{"kind": "country"}]}}
    # cache: faux ne_10m_admin_0_countries.geojson avec le pays du test
    ...
    jeu = build_dataset(tmp_path)  # adapter au nom/signature réels du module
    entree = ...  # la méta du test dans le dataset produit
    assert entree_a_une_geometrie_non_vide
```

Le squelette ci-dessus est à concrétiser avec les helpers réels du fichier — c'est la seule tâche où le plan ne peut pas donner le code final, les fixtures de `test_build_dataset.py` (520 lignes) faisant autorité. Exigence non négociable : le test doit poser `"geometry": None` dans le fichier geo et affirmer une géométrie non vide en sortie de build.

- [ ] **Step 2: Le voir échouer**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_dataset.py -q -k stripped`
Expected: FAIL — le build lit la géométrie `None` et produit une entrée sans géométrie (ou lève).

- [ ] **Step 3: Brancher le build sur `load_geo`**

Dans `cartometa/build/dataset.py`, remplacer :

```python
        geo = json.loads(chemins.geo.read_text("utf-8"))
        jeu.legacy_statuses += sum(
            1 for f in geo["features"] if f["properties"]["status"] not in STATUSES
        )
```

par :

```python
        records = load_geo(chemins, resolve=True)
        features = [records[k].to_feature() for k in sorted(records)]
        jeu.legacy_statuses += sum(
            1 for f in features if f["properties"]["status"] not in STATUSES
        )
```

puis remplacer chaque usage ultérieur de `geo["features"]` dans la même fonction par `features`. Import : ajouter `load_geo` à l'import existant de `cartometa.review.store` (le fichier importe déjà `CountryPaths` ; sinon l'ajouter).

- [ ] **Step 4: Vérifier**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_dataset.py tests/test_build_site.py tests/test_build_cli.py -q`
Expected: tous PASS.

- [ ] **Step 5: Commit**

```bash
git add cartometa/build/dataset.py tests/test_build_dataset.py
git commit -m "feat: le build resout les geometries elaguees via load_geo

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `test_real_data` — parse unique, déduplication, cache persistant

**Files:**
- Rewrite: `tests/test_real_data.py`

**Interfaces:**
- Consumes: `load_geo(paths, resolve=True)` (tâche 3), `write_json_atomic` (existant).
- Produces: mêmes 5 garanties qu'avant, mais : un seul parse des fichiers par session, une vérification de simplification par géométrie DISTINCTE, et un cache disque `data/cache/simplification_checks.json` qui évite de re-vérifier les géométries déjà passées. Relance sur données inchangées : quelques secondes au lieu de 32 min.

- [ ] **Step 1: Réécrire le fichier**

Remplacer intégralement `tests/test_real_data.py` par :

```python
import hashlib
import json
from pathlib import Path

import pytest
from shapely.geometry import shape

from cartometa.atomic_write import write_json_atomic
from cartometa.build.geometry import (
    DEFAULT_TOLERANCE,
    SIZE_DIVISOR,
    area_ratio,
    effective_tolerance,
    hausdorff,
    simplify_geometry,
)
from cartometa.review.store import CountryPaths, load_geo

pytestmark = pytest.mark.real_data

DATA_DIR = Path("data")
GEO_DIR = DATA_DIR / "geo"
STATUTS = {"validé", "rejeté"}
# Les verdicts memorises ne valent que pour ces parametres : les changer
# invalide tout le cache d'un coup, sans etat ambigu.
CACHE_VERSION = f"tolerance={DEFAULT_TOLERANCE}:divisor={SIZE_DIVISOR}"
CACHE_PATH = DATA_DIR / "cache" / "simplification_checks.json"


@pytest.fixture(scope="module")
def features():
    """Every country's features, resolved, parsed ONCE for the whole module.

    Before this fixture each of the five tests re-parsed the 99 files itself
    (~6 s each); the geometry work below is what must dominate, not json.
    Skips when there is not a single feature: walking zero features would give
    the four structural tests an undeserved green.
    """
    tout: list[tuple[str, dict]] = []
    for chemin in sorted(GEO_DIR.glob("*.geojson")):
        paths = CountryPaths(DATA_DIR, chemin.stem)
        for record in load_geo(paths, resolve=True).values():
            tout.append((chemin.name, record.to_feature()))
    if not tout:
        pytest.skip("no geometry: run cartometa-review")
    return tout


@pytest.fixture(scope="module")
def geometries_distinctes(features):
    """One representative per distinct geometry.

    37 US metas share the byte-identical national silhouette: checking it 37
    times multiplies the most expensive step (hausdorff, 46 s on the Canadian
    coastline) for no additional signal.
    """
    distinctes: dict[str, tuple[str, dict]] = {}
    for nom, feature in features:
        geometrie = feature["geometry"]
        if feature["properties"]["status"] != "validé" or geometrie is None:
            continue
        empreinte = hashlib.md5(
            json.dumps(geometrie, separators=(",", ":")).encode()
        ).hexdigest()
        identifiant = f"{nom}: {feature['properties']['id']}"
        distinctes.setdefault(empreinte, (identifiant, geometrie))
    return distinctes


def test_every_saved_geometry_is_valid(geometries_distinctes):
    for identifiant, geometrie in geometries_distinctes.values():
        geom = shape(geometrie)
        assert geom.is_valid, identifiant
        assert not geom.is_empty, identifiant


def test_only_the_two_expected_statuses_exist(features):
    for nom, feature in features:
        statut = feature["properties"]["status"]
        assert statut in STATUTS, f"{nom}: unexpected status {statut!r}"


def test_a_drawn_meta_always_has_a_geometry_and_its_pieces(features):
    for nom, feature in features:
        props = feature["properties"]
        if props["status"] != "validé":
            continue
        assert feature["geometry"] is not None, f"{nom}: {props['id']}"
        assert props["pieces"], f"{nom}: {props['id']} has no piece"


def test_a_rejected_meta_carries_no_geometry(features):
    for nom, feature in features:
        props = feature["properties"]
        if props["status"] == "rejeté":
            assert feature["geometry"] is None, f"{nom}: {props['id']}"


def _verdicts_connus() -> set[str]:
    """The geometry hashes already verified with the current parameters.

    Only successes are remembered: a failure must reappear at every run until
    the data is fixed. Deleting the file forces a full re-check (e.g. after a
    change to simplify_geometry itself).
    """
    if not CACHE_PATH.exists():
        return set()
    try:
        contenu = json.loads(CACHE_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return set()
    return set(contenu.get(CACHE_VERSION, []))


def test_simplification_meets_the_three_criteria_of_section_6_on_real_data(
    geometries_distinctes,
):
    """Acceptance criterion 5 (spec §14): the three checks of §6 — Hausdorff, area
    drift, validity — must pass on the real data, not only on synthetic geometries.

    The ×2 factor on the tolerance follows the convention already in place in
    `tests/test_build_geometry.py::test_the_hausdorff_distance_stays_under_the_effective_tolerance`:
    Douglas-Peucker guarantees a local deviation bounded by the tolerance, but the
    overall Hausdorff distance can accumulate two such deviations on either side of
    one segment.

    If this test fails, do not loosen the thresholds: a published geometry that
    drifts more than the spec promises is a substantive problem, not a test problem.
    """
    verifies = _verdicts_connus()
    violations: list[str] = []
    valides: list[str] = []
    pires = {"hausdorff_sur_tolerance": 0.0, "derive_aire": 0.0}

    for empreinte, (identifiant, original) in geometries_distinctes.items():
        if empreinte in verifies:
            continue
        simplifiee = simplify_geometry(original, DEFAULT_TOLERANCE)

        geom_simplifiee = shape(simplifiee)
        if not geom_simplifiee.is_valid:
            violations.append(f"{identifiant}: invalid geometry")
            continue
        if geom_simplifiee.is_empty:
            violations.append(f"{identifiant}: empty geometry")
            continue

        tolerance = effective_tolerance(original, DEFAULT_TOLERANCE)
        distance = hausdorff(original, simplifiee)
        ratio_tolerance = distance / tolerance if tolerance else 0.0
        conforme = True
        if distance > tolerance * 2:
            conforme = False
            violations.append(
                f"{identifiant}: Hausdorff {distance:.6f}° > "
                f"{tolerance * 2:.6f}° (2x effective tolerance {tolerance:.6f}°, "
                f"i.e. {ratio_tolerance:.2f}x)"
            )

        # Empirical threshold: at SIZE_DIVISOR = 500 the worst drift measured on
        # the real data is 3.3 %; 5 % keeps a deliberate margin above it.
        ratio = area_ratio(original, simplifiee)
        derive = abs(1.0 - ratio)
        if derive > 0.05:
            conforme = False
            violations.append(f"{identifiant}: area drift {derive * 100:.3f}% > 5%")

        if conforme:
            valides.append(empreinte)
        pires["hausdorff_sur_tolerance"] = max(
            pires["hausdorff_sur_tolerance"], ratio_tolerance
        )
        pires["derive_aire"] = max(pires["derive_aire"], derive)

    if valides:
        write_json_atomic(
            CACHE_PATH, {CACHE_VERSION: sorted(verifies | set(valides))}, indent=None
        )

    print(
        f"\n{len(verifies)} geometry(ies) already verified (cache), "
        f"{len(valides)} newly verified"
        f"\nworst Hausdorff / effective tolerance: {pires['hausdorff_sur_tolerance']:.3f}"
        f"\nworst area drift: {pires['derive_aire'] * 100:.4f}%"
    )
    assert not violations, (
        f"{len(violations)} geometry(ies) outside the §6 thresholds:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
```

Avant de lancer : vérifier que `SIZE_DIVISOR` est bien le nom exporté par `cartometa/build/geometry.py` (le commit 9fdb9a1 l'a fixé à 500) ; sinon reprendre le nom réel.

- [ ] **Step 2: Vérifier le comportement, cache vide**

Run: `.venv/Scripts/python.exe -m pytest tests/test_real_data.py -q -s 2>&1 | tail -8`
Expected: 5 PASS. Long (~10-15 min : premier remplissage du cache — chaque géométrie distincte paye son hausdorff une fois). Le print doit dire `0 geometry(ies) already verified`.

- [ ] **Step 3: Vérifier la relance à chaud**

Run: `.venv/Scripts/python.exe -m pytest tests/test_real_data.py -q -s 2>&1 | tail -8`
Expected: 5 PASS en moins d'une minute, print `N geometry(ies) already verified (cache), 0 newly verified`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_real_data.py
git commit -m "perf(tests): real_data deduplique les geometries et memorise les verdicts

Un seul parse par session au lieu de dix, une verification de
simplification par geometrie distincte (la silhouette US etait
verifiee 37 fois, 46 s de hausdorff chacune), et un cache disque des
verdicts reussis dans data/cache/ (gitignore). Relance sur donnees
inchangees : quelques secondes au lieu de 32 minutes. Supprimer le
cache force une re-verification complete.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Migration des fichiers `data/geo`

**Files:**
- Create (temporaire, non versionné) : script de migration dans le scratchpad
- Modify: les 99 `data/geo/*.geojson`

**Interfaces:**
- Consumes: `load_geo`/`save_geo` (tâche 3), `resolve_pieces`.
- Produces: fichiers élagués et vérifiés ; c'est LE commit qui fait maigrir le dépôt.

- [ ] **Step 1: Écrire le script de migration dans le scratchpad**

Le script, pour chaque `data/geo/*.geojson` : charge SANS résolution, mesure la dérive entre géométrie stockée et géométrie résolue pour chaque méta élagable, refuse de migrer si une dérive dépasse 1 % (Natural Earth aurait bougé depuis le traçage — décision humaine requise), sinon réécrit via `save_geo` :

```python
"""Migration one-shot : elague les geometries de reference de data/geo.

Verifie d'abord que chaque geometrie stockee correspond bien a la resolution
actuelle des pieces (l'ecart attendu est le seul arrondi a 5 decimales) : une
derive > 1 % signifierait que Natural Earth a change depuis le tracage, et ce
n'est pas au script d'en decider.
"""
import json
from pathlib import Path

from shapely.geometry import shape

from cartometa.review.pieces import resolve_pieces
from cartometa.review.store import REFERENCE_KINDS, CountryPaths, load_geo, save_geo

DATA = Path("data")
derives = []
total_avant = total_apres = 0

for chemin in sorted((DATA / "geo").glob("*.geojson")):
    paths = CountryPaths(DATA, chemin.stem)
    records = load_geo(paths)  # sans resolution : les geometries stockees
    for record in records.values():
        if record.geometry is None or not record.pieces:
            continue
        if not all(p.get("kind") in REFERENCE_KINDS for p in record.pieces):
            continue
        stockee = shape(record.geometry)
        resolue = resolve_pieces(record.pieces, paths.country, paths.cache)
        ecart = stockee.symmetric_difference(resolue).area / max(stockee.area, 1e-12)
        if ecart > 0.01:
            derives.append(f"{chemin.stem}/{record.id}: {ecart * 100:.2f} %")
        elif ecart > 0.001:
            print(f"  note {chemin.stem}/{record.id}: derive {ecart * 100:.3f} %")
    if derives:
        continue
    total_avant += chemin.stat().st_size
    save_geo(paths, records)
    total_apres += chemin.stat().st_size

if derives:
    raise SystemExit(
        "MIGRATION REFUSEE, derives Natural Earth a arbitrer :\n  "
        + "\n  ".join(derives)
    )
print(f"{total_avant / 1e6:.0f} Mo -> {total_apres / 1e6:.0f} Mo")
```

- [ ] **Step 2: L'exécuter**

Run: `.venv/Scripts/python.exe <scratchpad>/migre_geo.py`
Expected: pas de dérive bloquante, impression du gain (attendu : ~183 Mo → ~40 Mo). Si dérives listées : STOP, les montrer au propriétaire du dépôt, ne rien committer.

- [ ] **Step 3: Contrôler le résultat**

```bash
ls -la data/geo | sort -k5 -n -r | head -5
git diff --stat -- data/geo | tail -3
```

Expected: CA ~6 Mo, US ~2 Mo, RU nettement réduit. Puis relancer les garanties sur données réelles (le cache de la tâche 5 rend ça court — les géométries résolues sont identiques aux stockées d'avant migration à l'arrondi près, donc les hashes changent et une re-vérification partielle est NORMALE ; elle ne re-paye que les géométries dont le hash a bougé) :

Run: `.venv/Scripts/python.exe -m pytest tests/test_real_data.py -q`
Expected: 5 PASS.

- [ ] **Step 4: Commit des données**

```bash
git add data/geo
git commit -m "perf: elaguer les geometries de reference des 99 pays

<X> Mo -> <Y> Mo (reprendre les chiffres reels du script). Les metas
dont les pieces sont de pures references (country/admin1/clip)
stockaient la silhouette Natural Earth en copie : 37 fois la
silhouette US, 19 fois la canadienne. La geometrie se reconstruit a
la lecture via load_geo(resolve=True).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Vérification finale et chiffres

**Files:**
- Aucun changement de code attendu ; correction de docs si le format est documenté quelque part.

- [ ] **Step 1: Chercher la doc du format**

Run: `grep -rn "geometry" docs/*.md README.md CLAUDE.md 2>/dev/null | grep -i "geojson\|pieces"` — si un document décrit le format de `data/geo` (géométrie toujours présente), le mettre à jour pour mentionner l'élagage des références et `load_geo(resolve=True)`. Sinon, rien.

- [ ] **Step 2: Suite complète, deux fois**

Run: `.venv/Scripts/python.exe -m pytest -q` (deux exécutions successives, chronométrées)
Expected: tout vert les deux fois. Première exécution : les real_data re-vérifient ce qui a changé de hash après migration. Deuxième : ~1-2 min au total, dont quelques secondes de real_data. Noter les deux durées pour le rapport final.

- [ ] **Step 3: Commit éventuel de docs, puis rapport**

Rapporter au propriétaire : durée suite rapide / suite complète à froid / à chaud, tailles CA/US/RU avant-après, et le rappel que l'historique git garde les anciens blobs (le script `scripts/purge_historique.py` existe déjà si un nouveau passage de `git-filter-repo` est souhaité — décision du propriétaire, jamais automatique).

---

## Self-review (faite à l'écriture)

- Couverture : poids geojson → tâches 3, 4, 6 ; lenteur tests → tâches 1, 2, 5 ; garde-fous → gate de dérive (tâche 6), cache versionné par paramètres (tâche 5), round-trip octet-stable (tâche 3).
- Types cohérents : `load_geo(paths, resolve: bool = False)` partout ; `REFERENCE_KINDS` défini tâche 3, consommé tâche 6.
- Placeholder résiduel assumé : le corps exact du test de la tâche 4 dépend des fixtures de `test_build_dataset.py` (520 lignes) — l'exigence de comportement est spécifiée sans ambiguïté.
- Risque connu : `hausdorff()` reste 46 s par silhouette géante ; après déduplication + cache, il n'est payé qu'à l'apparition d'une géométrie nouvelle. C'est le compromis validé (real_data reste dans le run par défaut).
