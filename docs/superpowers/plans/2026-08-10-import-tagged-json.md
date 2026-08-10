# cartometa-import-tagged Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformer un JSON de points taggés (format carte GeoGuessr) en metas Cartometa « proposées » avec empreintes pré-dessinées, validables d'une touche dans `cartometa-review`.

**Architecture:** Nouveau module `cartometa/tagged/` (géométrie, rattachement pays, importeur, CLI) qui écrit dans `data/metas/<CC>-tagged.json` et `data/geo/<CC>.geojson` avec un nouveau statut « proposé ». Quatre retouches ciblées au socle : le statut dans la file de revue et le build, les trous dans les pièces `polygon`, la restauration d'une proposition au `U`, le cadrage de la carte sur les pièces préchargées.

**Tech Stack:** Python ≥ 3.14, shapely ≥ 2.1.2 (déjà présent — `concave_hull`, `STRtree`), aucune dépendance nouvelle. Tests pytest.

**Spec :** `docs/superpowers/specs/2026-08-10-import-tagged-json-design.md` — la lire avant de commencer.

## Global Constraints

- Lancer les tests avec `uv run python -m pytest` (jamais `uv run pytest` : politique Windows, `os error 4551`).
- Aucune dépendance nouvelle dans `pyproject.toml` (pas de numpy, pas de pyproj).
- Les statuts stockés gardent leur graphie française : `validé`, `rejeté`, et le nouveau `proposé`.
- Corridors : buffer **250 m** (largeur 500 m max). Zones : enveloppe concave gonflée de **10 km**. Seuils de chaînage : **5 km** (route), **40 km** (zone).
- Ids des metas importées : `tag-` + **6** hexadécimaux (SHA-1 de `nom_fichier|tag|pays`), déterministes.
- Les textes vont dans `data/metas/<CC>-tagged.json` (gitignoré — `data/metas/` l'est déjà en bloc, ne rien ajouter au `.gitignore`), les empreintes dans `data/geo/<CC>.geojson` (versionné).
- Ne jamais lancer l'import pendant qu'une session `cartometa-review` tourne (les deux réécrivent `data/geo/`) — l'import doit refuser si le port 8799 répond.
- Style du code : commentaires sobres qui expliquent les contraintes, à la manière du dépôt (voir `cartometa/review/store.py`). Code et docstrings dans la langue du fichier touché (les modules existants sont en anglais, les tests nomment leurs fonctions en anglais).

---

### Task 1: Statut « proposé » — modèle, file de revue, build

**Files:**
- Modify: `cartometa/models.py:16-21`
- Modify: `cartometa/review/store.py:230-233` (build_queue)
- Modify: `cartometa/build/dataset.py:144-146` (legacy_statuses)
- Test: `tests/test_store.py`, `tests/test_build_dataset.py`

**Interfaces:**
- Consumes: rien (première tâche).
- Produces: `cartometa.models.STATUS_PROPOSED: str = "proposé"` — importé par les tâches 3, 7. `STATUSES` reste `(STATUS_TRACED, STATUS_REJECTED)` : c'est le couple des **décisions**, `set_decision` n'accepte toujours qu'elles. `build_queue` inclut désormais dans la file par défaut toute meta dont le GeoRecord a le statut `proposé`, avec ses `pieces`.

- [ ] **Step 1: Écrire les tests qui échouent**

Dans `tests/test_store.py`, après `test_the_queue_skips_already_handled_metas_by_default` (réutiliser la fixture `paths` et le carré `CARRE` existants) :

```python
def test_a_proposed_meta_stays_in_the_default_queue_with_its_pieces(paths):
    piece = {"kind": "polygon", "ring": [[2.0, 48.0], [3.0, 48.0], [3.0, 49.0]]}
    save_geo(paths, {"aaaa": GeoRecord(
        id="aaaa", geometry=None, pieces=[piece], status=STATUS_PROPOSED,
    )})

    queue = build_queue(paths)

    item = next(i for i in queue["items"] if i["id"] == "aaaa")
    assert item["status"] == STATUS_PROPOSED
    assert item["pieces"] == [piece]
    # Une proposition n'est pas une décision : elle ne compte pas dans `done`.
    assert queue["done"] == 0
```

Ajouter `STATUS_PROPOSED` à l'import `from cartometa.models import …` du fichier de test.

Dans `tests/test_build_dataset.py`, s'inspirer de `_ecrire_pays` pour écrire un pays dont le geojson contient une feature `proposé` (avec `"pieces"` et une géométrie `_carre(0, 0, 1)`) et une feature `validé` :

```python
def test_a_proposed_footprint_is_neither_published_nor_counted_as_legacy(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "metas").mkdir(parents=True)
    (data_dir / "geo").mkdir(parents=True)
    (data_dir / "metas" / "PL.json").write_text(
        json.dumps([_meta("aaaa"), _meta("bbbb")]), "utf-8")
    (data_dir / "geo" / "PL.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": _carre(0, 0, 1), "properties": {
                "id": "aaaa", "status": "validé",
                "pieces": [{"kind": "polygon", "ring": [[0, 0], [1, 0], [1, 1]]}]}},
            {"type": "Feature", "geometry": _carre(2, 2, 1), "properties": {
                "id": "bbbb", "status": "proposé",
                "pieces": [{"kind": "polygon", "ring": [[2, 2], [3, 2], [3, 3]]}]}},
        ],
    }), "utf-8")

    jeu = build_dataset(data_dir, ["PL"])

    assert set(jeu.countries["PL"]["metas"]) == {"aaaa"}
    assert jeu.legacy_statuses == 0
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `uv run python -m pytest tests/test_store.py::test_a_proposed_meta_stays_in_the_default_queue_with_its_pieces tests/test_build_dataset.py::test_a_proposed_footprint_is_neither_published_nor_counted_as_legacy -v`
Expected: FAIL — `ImportError: cannot import name 'STATUS_PROPOSED'`.

- [ ] **Step 3: Implémenter**

Dans `cartometa/models.py`, remplacer le bloc statuts :

```python
# Two DECISION statuses: a geometry that exists was drawn by hand by
# construction. `proposé` is not a decision but a pre-drawn footprint waiting
# for one (cartometa-import-tagged): it stays in the review queue and is never
# published. `STATUSES` deliberately keeps only the decisions — that is what
# gates set_decision and the build's EXPORTABLE filter.
STATUS_TRACED = "validé"
STATUS_REJECTED = "rejeté"
STATUS_PROPOSED = "proposé"
STATUSES = (STATUS_TRACED, STATUS_REJECTED)
```

Dans `cartometa/review/store.py`, `build_queue`, remplacer :

```python
        record = geo.get(meta["id"])
        if record is not None and not include_all:
            continue
```

par :

```python
        record = geo.get(meta["id"])
        # A decided meta leaves the queue; a *proposed* one (imported footprint
        # awaiting yes/no) stays in it, pieces preloaded.
        if record is not None and record.status in STATUSES and not include_all:
            continue
```

Dans `cartometa/build/dataset.py`, importer `STATUS_PROPOSED` depuis `cartometa.models` et remplacer le calcul de `legacy_statuses` :

```python
        jeu.legacy_statuses += sum(
            1 for f in features
            if f["properties"]["status"] not in STATUSES + (STATUS_PROPOSED,)
        )
```

(`EXPORTABLE = (STATUS_TRACED,)` exclut déjà les proposées de la publication : rien d'autre à toucher.)

- [ ] **Step 4: Vérifier que tout passe**

Run: `uv run python -m pytest tests/test_store.py tests/test_build_dataset.py -v`
Expected: PASS (les nouveaux tests et tous les anciens).

- [ ] **Step 5: Commit**

```bash
git add cartometa/models.py cartometa/review/store.py cartometa/build/dataset.py tests/test_store.py tests/test_build_dataset.py
git commit -m "feat: statut « proposé » — en file avec ses pièces, jamais publié"
```

---

### Task 2: Pièces `polygon` à trous

**Files:**
- Modify: `cartometa/review/pieces.py:13-17,53-76`
- Modify: `cartometa/review/static/sketch.js:255-257` (geometryFor)
- Test: `tests/test_pieces.py`

**Interfaces:**
- Consumes: rien.
- Produces: le descripteur `{"kind": "polygon", "ring": [...], "holes": [[...], ...]}` — `holes` optionnel, liste d'anneaux au même format que `ring`. `resolve_pieces` le résout en `Polygon(ring, holes)`. `MAX_RING_POINTS` passe à 20 000 (les corridors importés dépassent les ~30 sommets d'un dessin à la main). La tâche 5 produit ces descripteurs.

- [ ] **Step 1: Écrire les tests qui échouent**

Dans `tests/test_pieces.py` (suivre le style des tests existants du fichier — les regarder d'abord) :

```python
def test_a_polygon_piece_can_carry_holes(tmp_path):
    piece = {
        "kind": "polygon",
        "ring": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
        "holes": [[[4.0, 4.0], [6.0, 4.0], [6.0, 6.0], [4.0, 6.0]]],
    }
    geometry = resolve_pieces([piece], "PL", tmp_path)
    # 10×10 moins le trou 2×2.
    assert geometry.area == pytest.approx(96.0)


def test_a_hole_must_be_a_valid_ring(tmp_path):
    piece = {
        "kind": "polygon",
        "ring": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
        "holes": [[[4.0, 4.0], [6.0, 4.0]]],  # deux sommets : pas un anneau
    }
    with pytest.raises(PieceError):
        resolve_pieces([piece], "PL", tmp_path)


def test_holes_default_to_absent(tmp_path):
    # Le dessin à la main n'envoie jamais `holes` : l'absence du champ est la norme.
    piece = {"kind": "polygon", "ring": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]}
    geometry = resolve_pieces([piece], "PL", tmp_path)
    assert geometry.area == pytest.approx(50.0)
```

Note : `resolve_pieces` avec une seule pièce `polygon` ne touche jamais Natural Earth (pas de kind `country`/`admin1`/`clip`), `tmp_path` en cache suffit — c'est le schéma des tests existants.

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `uv run python -m pytest tests/test_pieces.py -v -k hole`
Expected: le premier test FAIL (aire 100.0 au lieu de 96.0 : les trous sont ignorés), le deuxième FAIL (pas d'erreur levée).

- [ ] **Step 3: Implémenter**

Dans `cartometa/review/pieces.py` :

1. Le plafond et son commentaire :

```python
# A hand-drawn outline has a few dozen vertices; an imported corridor
# (cartometa-import-tagged) has thousands. The cap is still not an ergonomic
# limit but a safety rail: it stops a misbehaving client from running shapely
# over an endless list.
MAX_RING_POINTS = 20_000
```

2. Extraire la validation d'anneau de `_contour` et gérer `holes` :

```python
def _ring_points(ring: Any, label: str) -> list[tuple[float, float]]:
    if not isinstance(ring, (list, tuple)):
        raise PieceError(f"an outline needs {label} = [[lon, lat], ...]")
    if not (MIN_RING_POINTS <= len(ring) <= MAX_RING_POINTS):
        raise PieceError(
            f"a {label} needs between {MIN_RING_POINTS} and {MAX_RING_POINTS} "
            f"vertices, got {len(ring)}"
        )
    points = []
    for vertex in ring:
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 2:
            raise PieceError(f"unreadable vertex: {vertex!r}")
        points.append(_check_lonlat(vertex[0], vertex[1]))
    return points


def _contour(piece: dict) -> BaseGeometry:
    points = _ring_points(piece.get("ring"), "ring")
    holes = piece.get("holes") or []
    if not isinstance(holes, (list, tuple)):
        raise PieceError("holes must be a list of rings")
    shells = [_ring_points(hole, "hole") for hole in holes]

    geom = Polygon(points, shells)
    if not geom.is_valid:
        # An outline drawn with the mouse self-intersects easily. `buffer(0)`
        # repairs it without betraying the intent — the same treatment as damaged
        # Natural Earth outlines (cf. country_geometry).
        geom = geom.buffer(0)
    if geom.is_empty or geom.area <= 0.0:
        raise PieceError("outline with zero area")
    return geom
```

3. Dans `cartometa/review/static/sketch.js`, `geometryFor`, remplacer la branche `polygon` :

```js
    if (piece.kind === 'polygon') {
      // Les trous n'existent que sur les pièces importées (corridors) : le
      // dessin à la souris n'en produit jamais.
      const close = (ring) => [...ring, ring[0]];
      return {
        type: 'Polygon',
        coordinates: [close(piece.ring), ...(piece.holes || []).map(close)],
      };
    }
```

- [ ] **Step 4: Vérifier que tout passe**

Run: `uv run python -m pytest tests/test_pieces.py tests/test_store.py -v`
Expected: PASS (y compris les anciens tests de `_contour`).

- [ ] **Step 5: Commit**

```bash
git add cartometa/review/pieces.py cartometa/review/static/sketch.js tests/test_pieces.py
git commit -m "feat: trous dans les pièces polygon (rocades des corridors importés)"
```

---

### Task 3: `U` restaure une proposition au lieu de l'effacer

**Files:**
- Modify: `cartometa/review/store.py` (nouvelle fonction après `clear_decision`)
- Modify: `cartometa/review/server.py:182-183` (route `/api/undo`)
- Modify: `cartometa/review/static/app.js:191-213` (undo)
- Test: `tests/test_store.py`, `tests/test_review_server.py`

**Interfaces:**
- Consumes: `STATUS_PROPOSED` (tâche 1).
- Produces: `restore_proposal(paths: CountryPaths, meta_id: str, pieces: list[dict]) -> None` dans `store.py` ; `apply_undo(meta_id: str, restore: dict | None) -> None` dans `server.py` (même schéma que `apply_decision`, testable sans HTTP). La route POST `/api/undo` accepte un champ optionnel `restore: {"status": "proposé", "pieces": [...]}` ; sans lui, comportement actuel (`clear_decision`).

Contexte pour l'implémenteur : aujourd'hui `U` appelle `clear_decision`, qui **supprime** l'enregistrement. Pour une meta importée, cela détruirait la proposition (pièces comprises) alors qu'elle est régénérable seulement en relançant l'import. Le client connaît l'état d'origine (l'item de la file, chargé au démarrage, porte `status` et `pieces`) : il le renvoie pour restauration.

- [ ] **Step 1: Écrire les tests qui échouent**

Dans `tests/test_store.py` :

```python
def test_restore_proposal_puts_the_imported_footprint_back(paths):
    piece = {"kind": "polygon", "ring": [[2.0, 48.0], [3.0, 48.0], [3.0, 49.0]]}
    set_decision(paths, "aaaa", STATUS_TRACED, CARRE, [piece])

    restore_proposal(paths, "aaaa", [piece])

    record = load_geo(paths)["aaaa"]
    assert record.status == STATUS_PROPOSED
    assert record.pieces == [piece]
    assert record.geometry is None


def test_restore_proposal_refuses_an_unknown_meta(paths):
    with pytest.raises(UnknownMetaError):
        restore_proposal(paths, "zzzz", [])
```

Dans `tests/test_review_server.py`, les tests appellent les helpers du module serveur directement (schéma de `server.apply_decision`, fixture `paths` existante qui remplit `server.STATE`). Ajouter `STATUS_PROPOSED` aux imports de `cartometa.models`, puis :

```python
def test_undo_restores_an_imported_proposal(paths):
    piece = {"kind": "rect", "bounds": [2, 48, 3, 49]}
    server.apply_decision("aaaa", STATUS_TRACED, [piece])

    server.apply_undo("aaaa", {"status": STATUS_PROPOSED, "pieces": [piece]})

    record = load_geo(paths)["aaaa"]
    assert record.status == STATUS_PROPOSED
    assert record.pieces == [piece]
    assert record.geometry is None


def test_undo_without_restore_erases_the_record(paths):
    server.apply_decision("aaaa", STATUS_TRACED, [{"kind": "country"}])

    server.apply_undo("aaaa", None)

    assert "aaaa" not in load_geo(paths)
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `uv run python -m pytest tests/test_store.py -v -k restore`
Expected: FAIL — `ImportError: cannot import name 'restore_proposal'`.

- [ ] **Step 3: Implémenter**

Dans `cartometa/review/store.py`, importer `STATUS_PROPOSED` depuis `cartometa.models`, puis après `clear_decision` :

```python
def restore_proposal(paths: CountryPaths, meta_id: str, pieces: list[dict]) -> None:
    """Put an imported proposal back after its decision is undone.

    clear_decision would erase the record entirely — correct for a meta whose
    blank state IS the absence of a record, destructive for an imported one
    whose pre-drawn pieces only exist by re-running the import. The client owns
    the original state (the queue item it loaded) and sends it back.
    """
    if meta_id not in {meta["id"] for meta in load_metas(paths)}:
        raise UnknownMetaError(f"unknown meta: {meta_id!r}")
    records = load_geo(paths)
    records[meta_id] = GeoRecord(
        id=meta_id, geometry=None, pieces=list(pieces), status=STATUS_PROPOSED
    )
    save_geo(paths, records)
```

Dans `cartometa/review/server.py`, importer `restore_proposal` depuis `cartometa.review.store` et `STATUS_PROPOSED` depuis `cartometa.models`. Ajouter après `apply_decision` :

```python
def apply_undo(meta_id: str, restore: dict | None) -> None:
    """Undo a decision — back to blank, or back to the imported proposal.

    An imported meta was never blank: its pre-drawn pieces only exist by
    re-running the import. The client, who loaded them with the queue, sends
    them back for restoration.
    """
    if isinstance(restore, dict) and restore.get("status") == STATUS_PROPOSED:
        restore_proposal(paths(), meta_id, restore.get("pieces") or [])
    else:
        clear_decision(paths(), meta_id)
```

et remplacer la branche undo de la route :

```python
            elif route == "/api/undo":
                apply_undo(payload["id"], payload.get("restore"))
```

Dans `cartometa/review/static/app.js`, fonction `undo()`, remplacer la ligne `await postJSON('/api/undo', { id: last.id });` par :

```js
    // Une meta importée « proposé » ne doit pas redevenir vierge : U restaure
    // l'état que la file avait chargé (statut et pièces d'origine).
    const item = queue.find((q) => q.id === last.id);
    const payload = { id: last.id };
    if (item && item.status === 'proposé') {
      payload.restore = { status: item.status, pieces: item.pieces };
    }
    await postJSON('/api/undo', payload);
```

Vérifier dans `sketch.js` que `reset(pieces)` **copie** la liste reçue (par ex. `this.pieces = [...pieces]`) et ne garde pas la référence de `item.pieces` — sinon les retouches faites au dessin avant la décision contamineraient l'état restauré. Si `reset` garde la référence, corriger en copiant.

- [ ] **Step 4: Vérifier que tout passe**

Run: `uv run python -m pytest tests/test_store.py tests/test_review_server.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cartometa/review/store.py cartometa/review/server.py cartometa/review/static/app.js cartometa/review/static/sketch.js tests/test_store.py tests/test_review_server.py
git commit -m "feat: U restaure une proposition importée au lieu de l'effacer"
```

---

### Task 4: Cadrer la carte sur les pièces préchargées

**Files:**
- Modify: `cartometa/review/static/app.js:92-116` (frame)

**Interfaces:**
- Consumes: le format des pièces (`rect.bounds = [west, south, east, north]`, `polygon.ring = [[lon, lat], …]`).
- Produces: rien (changement d'affichage pur). Pas de test automatisé : le dépôt n'a pas de harnais JS ; la vérification est visuelle, en tâche 9.

Contexte : `frame()` cadre aujourd'hui le point Maps, sinon la silhouette du pays. Un corridor de 500 m perdu dans l'Ukraine serait invisible au zoom pays : les pièces à coordonnées doivent primer.

- [ ] **Step 1: Implémenter**

Dans `cartometa/review/static/app.js`, ajouter au-dessus de `frame()` :

```js
function piecesBounds(pieces) {
  // Seules les pièces à coordonnées cadrent ; `country`, `admin1` et `clip`
  // n'en portent pas et retombent sur le cadrage existant.
  const latlngs = [];
  for (const piece of pieces || []) {
    if (piece.kind === 'rect') {
      const [west, south, east, north] = piece.bounds;
      latlngs.push([south, west], [north, east]);
    } else if (piece.kind === 'polygon') {
      for (const [lon, lat] of piece.ring) latlngs.push([lat, lon]);
    }
  }
  return latlngs.length ? L.latLngBounds(latlngs) : null;
}
```

et en tête de `frame(item)`, avant le test `if (item.latlon)` :

```js
  // Une empreinte préchargée (meta importée, ou --all) est le vrai sujet :
  // on la cadre elle, pas le pays entier où un corridor de 500 m disparaît.
  const bounds = piecesBounds(item.pieces);
  if (bounds) {
    map.fitBounds(bounds, { padding: [20, 20] });
    return;
  }
```

- [ ] **Step 2: Vérification statique et suite complète**

Run: `node --check cartometa/review/static/app.js` (syntaxe seulement — préfixer par `"C:\Program Files\nodejs\node"` si `node` n'est pas dans le PATH), puis `uv run python -m pytest`
Expected: syntaxe OK, suite verte.

- [ ] **Step 3: Commit**

```bash
git add cartometa/review/static/app.js
git commit -m "feat: la revue cadre la carte sur les pièces préchargées"
```

---

### Task 5: Géométrie des corridors et des zones

**Files:**
- Create: `cartometa/tagged/__init__.py` (vide)
- Create: `cartometa/tagged/geometry.py`
- Test: `tests/test_tagged_geometry.py`

**Interfaces:**
- Consumes: `MAX_RING_POINTS` (tâche 2), `simplify_geometry` (existant, pour le test de régression).
- Produces, dans `cartometa.tagged.geometry` — les points sont toujours `[(lat, lng), …]`, les géométries retournées en WGS84 :
  - `corridor_geometry(points, buffer_m: float = 250.0, link_km: float = 5.0) -> BaseGeometry`
  - `zone_geometry(points, hull_buffer_km: float = 10.0, link_km: float = 40.0, ratio: float = 0.4) -> BaseGeometry`
  - `geometry_to_pieces(geom: BaseGeometry, simplify_deg: float) -> list[dict]` — pièces `{"kind": "polygon", "ring": …}` (+ `"holes"` si trous), anneaux **ouverts** (sans sommet de fermeture, comme ceux du client JS), chaque anneau ≤ `MAX_RING_POINTS`.
  - `mst_edges(xy: list[tuple[float, float]]) -> list[tuple[int, int, float]]` (exposé pour les tests).

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_tagged_geometry.py` :

```python
import math

import pytest
from shapely.geometry import Point, mapping, shape

from cartometa.build.geometry import simplify_geometry
from cartometa.tagged.geometry import (
    corridor_geometry,
    geometry_to_pieces,
    mst_edges,
    zone_geometry,
)

# ~0.009° de longitude ≈ 1 km vers 50° N (facteur cos appliqué par la projection).
KM_LON = 1 / (111.320 * math.cos(math.radians(50.0)))
KM_LAT = 1 / 110.574


def _chain(n, step_km=2.0, lat=50.0, lng0=20.0):
    """n points alignés ouest→est, espacés de step_km."""
    return [(lat, lng0 + i * step_km * KM_LON) for i in range(n)]


def test_a_chain_of_points_becomes_one_ribbon():
    geom = corridor_geometry(_chain(10))
    assert geom.geom_type == "Polygon"
    # 18 km de long sur 500 m de large : l'aire est celle d'un ruban, pas d'une enveloppe.
    aire_km2 = geom.area * 110.574 * 111.320 * math.cos(math.radians(50.0))
    assert aire_km2 == pytest.approx(18 * 0.5, rel=0.15)


def test_two_far_apart_segments_become_two_ribbons():
    points = _chain(5) + _chain(5, lng0=21.0)  # ~40 km d'écart, > link_km
    geom = corridor_geometry(points)
    assert geom.geom_type == "MultiPolygon"
    assert len(geom.geoms) == 2


def test_an_isolated_point_becomes_a_disc():
    geom = corridor_geometry([(50.0, 20.0)])
    assert geom.geom_type == "Polygon"
    assert geom.contains(Point(20.0, 50.0))


def test_a_closed_loop_keeps_its_hole():
    # Une rocade : 36 points sur un cercle de 5 km de rayon.
    centre_lat, centre_lng = 50.0, 20.0
    points = [
        (centre_lat + 5 * KM_LAT * math.sin(a), centre_lng + 5 * KM_LON * math.cos(a))
        for a in [i * 2 * math.pi / 36 for i in range(36)]
    ]
    geom = corridor_geometry(points)
    assert not geom.contains(Point(centre_lng, centre_lat))
    pieces = geometry_to_pieces(geom, simplify_deg=0.0005)
    assert any(piece.get("holes") for piece in pieces)


def test_mst_links_every_point():
    xy = [(0.0, 0.0), (1.0, 0.0), (0.5, 5.0)]
    edges = mst_edges(xy)
    assert len(edges) == 2
    assert {i for a, b, _ in edges for i in (a, b)} == {0, 1, 2}


def test_two_clusters_become_two_hulls():
    # Deux nuages de 3×3 points espacés de 15 km, à ~600 km l'un de l'autre.
    def _grid(lng0):
        return [
            (50.0 + i * 15 * KM_LAT, lng0 + j * 15 * KM_LON)
            for i in range(3) for j in range(3)
        ]
    geom = zone_geometry(_grid(20.0) + _grid(28.0))
    assert geom.geom_type == "MultiPolygon"
    assert len(geom.geoms) == 2


def test_a_hull_covers_all_its_points_with_margin():
    points = [(50.0, 20.0), (50.3, 20.5), (50.1, 20.9), (49.8, 20.4)]
    geom = zone_geometry(points)
    for lat, lng in points:
        # Le buffer de 10 km met chaque point nettement à l'intérieur.
        assert geom.contains(Point(lng, lat).buffer(0.01))


def test_a_pair_of_points_becomes_a_capsule():
    geom = zone_geometry([(50.0, 20.0), (50.0, 20.1)])
    assert geom.geom_type == "Polygon"
    assert geom.contains(Point(20.05, 50.0))


def test_pieces_rings_are_open_and_capped():
    geom = corridor_geometry(_chain(50))
    pieces = geometry_to_pieces(geom, simplify_deg=0.0005)
    for piece in pieces:
        assert piece["kind"] == "polygon"
        assert piece["ring"][0] != piece["ring"][-1]
        assert len(piece["ring"]) <= 20_000


def test_a_corridor_survives_the_build_simplification():
    # Régression : effective_tolerance borne la tolérance par la largeur moyenne,
    # un ruban de 500 m ne doit pas être pulvérisé par le défaut de 0.01°.
    geom = corridor_geometry(_chain(30))
    simplifiee = shape(simplify_geometry(mapping(geom)))
    assert simplifiee.area == pytest.approx(geom.area, rel=0.25)
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `uv run python -m pytest tests/test_tagged_geometry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.tagged'`.

- [ ] **Step 3: Implémenter**

Créer `cartometa/tagged/__init__.py` vide, puis `cartometa/tagged/geometry.py` :

```python
from __future__ import annotations

import math

from shapely import concave_hull
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from cartometa.review.pieces import MAX_RING_POINTS

KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON = 111.320


def _projector(points):
    """(to_xy, to_wgs) for a local point cloud, in kilometres.

    A flat scaling by cos(mean latitude): at country scale and for buffers of
    250 m to 10 km the distortion is negligible, and it spares a pyproj
    dependency. Known limit, accepted: clouds straddling the antimeridian or a
    whole continent distort — the per-country split keeps real inputs local.
    """
    lat0 = sum(lat for lat, _ in points) / len(points)
    kx = KM_PER_DEG_LON * math.cos(math.radians(lat0))
    ky = KM_PER_DEG_LAT

    def to_xy(lng, lat):
        return (lng * kx, lat * ky)

    def to_wgs(x, y):
        return (x / kx, y / ky)

    return to_xy, to_wgs


def mst_edges(xy: list[tuple[float, float]]) -> list[tuple[int, int, float]]:
    """Minimum spanning tree (Prim, O(n²) pure Python), edges (i, j, km).

    ~7 M distance evaluations for the worst real tag (2 592 points): a few
    seconds, which does not justify a numpy dependency.
    """
    n = len(xy)
    if n < 2:
        return []
    in_tree = [False] * n
    dist = [math.inf] * n
    parent = [0] * n
    in_tree[0] = True
    for j in range(1, n):
        dist[j] = math.dist(xy[0], xy[j])
    edges = []
    for _ in range(n - 1):
        d, j = min(
            (d, j) for j, (d, seen) in enumerate(zip(dist, in_tree)) if not seen
        )
        in_tree[j] = True
        dist[j] = math.inf
        edges.append((parent[j], j, d))
        for k in range(n):
            if not in_tree[k]:
                dk = math.dist(xy[j], xy[k])
                if dk < dist[k]:
                    dist[k] = dk
                    parent[k] = j
    return edges


def _clusters(xy: list[tuple[float, float]], link_km: float) -> list[list[int]]:
    """Connected components of the MST once edges longer than link_km are cut."""
    parent = list(range(len(xy)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b, d in mst_edges(xy):
        if d <= link_km:
            parent[find(a)] = find(b)
    groups: dict[int, list[int]] = {}
    for i in range(len(xy)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def corridor_geometry(
    points, buffer_m: float = 250.0, link_km: float = 5.0
) -> BaseGeometry:
    """A faithful ribbon around the reconstructed route (width = 2 × buffer_m).

    MST edges longer than link_km are cut: they would bridge distinct road
    segments. A point left without any edge becomes a disc.
    """
    to_xy, to_wgs = _projector(points)
    xy = [to_xy(lng, lat) for lat, lng in points]
    edges = [e for e in mst_edges(xy) if e[2] <= link_km]
    linked = {i for a, b, _ in edges for i in (a, b)}
    parts: list[BaseGeometry] = [LineString([xy[a], xy[b]]) for a, b, _ in edges]
    parts += [Point(p) for i, p in enumerate(xy) if i not in linked]
    ribbon = unary_union(parts).buffer(buffer_m / 1000.0)
    return transform(to_wgs, ribbon)


def zone_geometry(
    points,
    hull_buffer_km: float = 10.0,
    link_km: float = 40.0,
    ratio: float = 0.4,
) -> BaseGeometry:
    """One inflated concave hull per cluster of points.

    Clusters of one or two points have no hull: the buffer alone gives a disc
    or a capsule.
    """
    to_xy, to_wgs = _projector(points)
    xy = [to_xy(lng, lat) for lat, lng in points]
    shapes = []
    for cluster in _clusters(xy, link_km):
        cloud = MultiPoint([xy[i] for i in cluster])
        core = concave_hull(cloud, ratio=ratio) if len(cluster) >= 3 else cloud
        shapes.append(core.buffer(hull_buffer_km))
    return transform(to_wgs, unary_union(shapes))


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon" and g.area > 0]


def geometry_to_pieces(geom: BaseGeometry, simplify_deg: float) -> list[dict]:
    """One `polygon` piece per polygon, rings open, capped at MAX_RING_POINTS.

    Simplified before conversion so the versioned geojson stays bounded; the
    tolerance doubles until every ring fits under resolve_pieces' safety rail —
    a corridor over thousands of points can exceed it at the first tolerance.
    """
    tolerance = simplify_deg
    for _ in range(12):
        simplified = geom.simplify(tolerance, preserve_topology=True)
        pieces = []
        fits = True
        for poly in _polygons(simplified):
            rings = [poly.exterior, *poly.interiors]
            if any(len(r.coords) - 1 > MAX_RING_POINTS for r in rings):
                fits = False
                break
            piece = {"kind": "polygon", "ring": [list(c) for c in poly.exterior.coords[:-1]]}
            holes = [
                [list(c) for c in interior.coords[:-1]]
                for interior in poly.interiors
                if len(interior.coords) - 1 >= 3
            ]
            if holes:
                piece["holes"] = holes
            pieces.append(piece)
        if fits and pieces:
            return pieces
        tolerance *= 2
    raise ValueError("geometry too dense: no tolerance fits under MAX_RING_POINTS")
```

- [ ] **Step 4: Vérifier que tout passe**

Run: `uv run python -m pytest tests/test_tagged_geometry.py -v`
Expected: PASS. Si `test_a_chain_of_points_becomes_one_ribbon` échoue sur l'aire, vérifier le facteur de conversion °→km du test avant de soupçonner la projection.

- [ ] **Step 5: Commit**

```bash
git add cartometa/tagged/__init__.py cartometa/tagged/geometry.py tests/test_tagged_geometry.py
git commit -m "feat: géométrie des corridors et zones depuis un nuage de points taggés"
```

---

### Task 6: Rattachement des points au pays

**Files:**
- Create: `cartometa/tagged/countries.py`
- Test: `tests/test_tagged_countries.py`

**Interfaces:**
- Consumes: `ensure_dataset(cache_dir)` de `cartometa.geo.reference` (télécharge/lit le Natural Earth admin-0 en cache).
- Produces: `CountryIndex(cache_dir: Path)` avec la méthode `country_of(lat: float, lng: float) -> str | None` — code ISO alpha-2 majuscule, ou `None` si le point est à plus de ~10 km de tout pays.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_tagged_countries.py`. Le cache est simulé : `ensure_dataset` lit `cache_dir / DATASET_NAME` s'il existe, aucun téléchargement (même schéma que `tests/test_reference.py` — le consulter).

```python
import json

import pytest

from cartometa.geo.reference import DATASET_NAME
from cartometa.tagged.countries import CountryIndex


def _pays(code, west, south, east, north):
    return {
        "type": "Feature",
        "properties": {"ISO_A2": code, "ISO_A2_EH": code},
        "geometry": {"type": "Polygon", "coordinates": [[
            [west, south], [east, south], [east, north], [west, north], [west, south],
        ]]},
    }


@pytest.fixture
def index(tmp_path):
    (tmp_path / DATASET_NAME).write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            _pays("AA", 0.0, 0.0, 10.0, 10.0),
            _pays("BB", 20.0, 0.0, 30.0, 10.0),
            # Code manquant, à la façon Natural Earth : jamais rattachable.
            _pays("-99", 40.0, 0.0, 50.0, 10.0),
        ],
    }), "utf-8")
    return CountryIndex(tmp_path)


def test_a_point_lands_in_its_country(index):
    assert index.country_of(5.0, 5.0) == "AA"
    assert index.country_of(5.0, 25.0) == "BB"


def test_a_point_just_offshore_snaps_to_the_nearest_country(index):
    # 0.05° à l'ouest de AA : dans le rayon de rattachement (~10 km).
    assert index.country_of(5.0, -0.05) == "AA"


def test_a_point_far_from_everything_is_dropped(index):
    assert index.country_of(5.0, 15.0) is None


def test_a_country_without_iso_code_never_matches(index):
    assert index.country_of(5.0, 45.0) is None
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `uv run python -m pytest tests/test_tagged_countries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.tagged.countries'`.

- [ ] **Step 3: Implémenter**

Créer `cartometa/tagged/countries.py` :

```python
from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from cartometa.geo.reference import ensure_dataset

# Snapping radius for a point inside no polygon (sea, Natural Earth coastline
# gap): beyond ~10 km it is dropped rather than force-attached.
NEAREST_MAX_DEG = 0.09


class CountryIndex:
    """Point -> ISO alpha-2 code, from Natural Earth admin-0.

    Built once per import. The STRtree holds the *parts* of the multipolygons,
    not the whole countries: querying 5 000 points against entire geometries
    would drag every lookup through the full Russia polygon.
    """

    def __init__(self, cache_dir: Path) -> None:
        data = json.loads(ensure_dataset(cache_dir).read_text("utf-8"))
        self._codes: list[str] = []
        parts = []
        for feature in data["features"]:
            props = feature["properties"]
            code = props.get("ISO_A2_EH") or props.get("ISO_A2")
            # Natural Earth encodes a missing code as "-99".
            if not code or code == "-99":
                continue
            geom = shape(feature["geometry"])
            if not geom.is_valid:
                geom = geom.buffer(0)
            for part in geom.geoms if geom.geom_type == "MultiPolygon" else [geom]:
                parts.append(part)
                self._codes.append(code.upper())
        self._tree = STRtree(parts)

    def country_of(self, lat: float, lng: float) -> str | None:
        point = Point(lng, lat)
        hits = self._tree.query(point, predicate="intersects")
        if len(hits):
            return self._codes[hits[0]]
        near = self._tree.query_nearest(point, max_distance=NEAREST_MAX_DEG)
        if len(near):
            return self._codes[near[0]]
        return None
```

- [ ] **Step 4: Vérifier que tout passe**

Run: `uv run python -m pytest tests/test_tagged_countries.py -v`
Expected: PASS. Si `query`/`query_nearest` retournent autre chose que des indices (selon la version shapely), corriger l'accès aux résultats — la version épinglée est ≥ 2.1.2 où ce sont des tableaux d'indices.

- [ ] **Step 5: Commit**

```bash
git add cartometa/tagged/countries.py tests/test_tagged_countries.py
git commit -m "feat: rattachement point -> pays via Natural Earth admin-0"
```

---

### Task 7: L'importeur — parsing, regroupement, écriture

**Files:**
- Modify: `cartometa/models.py` (ORIGIN_TAGGED)
- Modify: `cartometa/review/store.py:40-56` (CountryPaths.tagged_metas) et `store.py:78-84` (load_metas)
- Create: `cartometa/tagged/importer.py`
- Test: `tests/test_tagged_importer.py`

**Interfaces:**
- Consumes: `corridor_geometry`, `zone_geometry`, `geometry_to_pieces` (tâche 5) ; `CountryIndex` (tâche 6) ; `STATUS_PROPOSED`, `STATUSES`, `GeoRecord`, `TIER_MANUAL` (models) ; `save_geo`, `load_geo`, `read_json_list`, `CountryPaths` (store) ; `write_json_atomic`.
- Produces, dans `cartometa.tagged.importer` :
  - `import_tagged(data_dir: Path, file: Path, *, mode: str, category: str, buffer_m: float = 250.0, link_km: float | None = None, hull_buffer_km: float = 10.0, dry_run: bool = False) -> ImportReport`
  - `ImportReport` : `source: str`, `mode: str`, `untagged: int`, `unplaced: int`, `rows: list[TagReport]` ; `TagReport` : `tag: str`, `country: str`, `points: int`, `pieces: int`, `action: str` (`"écrite"`, `"réécrite"`, `"inchangée"`, `"sautée (décidée)"`).
  - `TaggedFileError(ValueError)` — fichier illisible, session de revue active, collision d'ids.
  - `proposal_id(name: str, tag: str, country: str) -> str` (exposé pour les tests).
  - `cartometa.models.ORIGIN_TAGGED = "tagged"`.
  - `CountryPaths.tagged_metas -> data/metas/<CC>-tagged.json`, chargé par `load_metas` entre RMRG et manuel.

Sémantique d'écriture (de la spec) : un GeoRecord existant au statut `validé` ou `rejeté` n'est **jamais** touché (« sautée (décidée) ») — toute retouche humaine passe par une décision, le statut la protège donc. Un enregistrement encore `proposé` est régénéré (les changements de paramètres se propagent). L'`extracted_at` d'une meta déjà présente est conservé pour que deux runs identiques produisent des fichiers identiques octet pour octet.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_tagged_importer.py` :

```python
import json

import pytest

from cartometa.geo.reference import DATASET_NAME
from cartometa.models import STATUS_PROPOSED, STATUS_TRACED, GeoRecord
from cartometa.review.store import CountryPaths, build_queue, load_geo, load_metas, save_geo
from cartometa.tagged.importer import ImportReport, TaggedFileError, import_tagged, proposal_id


def _point(lat, lng, tags):
    return {"lat": lat, "lng": lng, "extra": {"tags": tags}}


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    (d / "cache").mkdir(parents=True)
    (d / "cache" / DATASET_NAME).write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"ISO_A2": c, "ISO_A2_EH": c},
             "geometry": {"type": "Polygon", "coordinates": [[
                 [w, 0.0], [w + 10.0, 0.0], [w + 10.0, 10.0], [w, 10.0], [w, 0.0],
             ]]}}
            for c, w in (("AA", 0.0), ("BB", 20.0))
        ],
    }), "utf-8")
    return d


def _source(tmp_path, points, name="fichier test"):
    f = tmp_path / "source.json"
    f.write_text(json.dumps({"name": name, "customCoordinates": points}), "utf-8")
    return f


def test_one_meta_per_tag_and_country(data_dir, tmp_path):
    src = _source(tmp_path, [
        _point(5.0, 5.0, ["Ring"]), _point(5.01, 5.01, ["Ring"]),
        _point(5.0, 25.0, ["Ring"]),          # même tag, autre pays
        _point(5.02, 5.02, ["Short", "Ring"]),  # deux tags -> deux metas
    ])

    report = import_tagged(data_dir, src, mode="route", category="car")

    aa = CountryPaths(data_dir, "AA")
    metas = {m["title"]: m for m in load_metas(aa)}
    assert set(metas) == {"Ring", "Short"}
    assert metas["Ring"]["description"] == "Ring"
    assert metas["Ring"]["category"] == "car"
    assert metas["Ring"]["origin"] == "tagged"
    assert metas["Ring"]["id"] == proposal_id("fichier test", "Ring", "AA")
    bb = CountryPaths(data_dir, "BB")
    assert {m["title"] for m in load_metas(bb)} == {"Ring"}
    assert {(r.tag, r.country) for r in report.rows} == {
        ("Ring", "AA"), ("Ring", "BB"), ("Short", "AA"),
    }


def test_proposals_land_in_the_review_queue_with_pieces(data_dir, tmp_path):
    src = _source(tmp_path, [_point(5.0, 5.0, ["Ring"]), _point(5.01, 5.01, ["Ring"])])
    import_tagged(data_dir, src, mode="route", category="car")

    queue = build_queue(CountryPaths(data_dir, "AA"))

    (item,) = queue["items"]
    assert item["status"] == STATUS_PROPOSED
    assert item["pieces"][0]["kind"] == "polygon"


def test_rerunning_the_import_changes_nothing(data_dir, tmp_path):
    src = _source(tmp_path, [_point(5.0, 5.0, ["Ring"]), _point(5.01, 5.01, ["Ring"])])
    aa = CountryPaths(data_dir, "AA")

    import_tagged(data_dir, src, mode="route", category="car")
    before = (aa.tagged_metas.read_bytes(), aa.geo.read_bytes())
    report = import_tagged(data_dir, src, mode="route", category="car")

    assert (aa.tagged_metas.read_bytes(), aa.geo.read_bytes()) == before
    assert all(r.action == "inchangée" for r in report.rows)


def test_a_decided_meta_is_never_overwritten(data_dir, tmp_path):
    src = _source(tmp_path, [_point(5.0, 5.0, ["Ring"]), _point(5.01, 5.01, ["Ring"])])
    import_tagged(data_dir, src, mode="route", category="car")
    aa = CountryPaths(data_dir, "AA")
    pid = proposal_id("fichier test", "Ring", "AA")
    mine = {"kind": "polygon", "ring": [[5.0, 5.0], [6.0, 5.0], [6.0, 6.0]]}
    records = load_geo(aa)
    records[pid] = GeoRecord(id=pid, geometry=None, pieces=[mine], status=STATUS_TRACED)
    save_geo(aa, records)

    report = import_tagged(data_dir, src, mode="route", category="car")

    assert load_geo(aa)[pid].status == STATUS_TRACED
    assert load_geo(aa)[pid].pieces == [mine]
    (row,) = report.rows
    assert row.action == "sautée (décidée)"


def test_dry_run_writes_nothing(data_dir, tmp_path):
    src = _source(tmp_path, [_point(5.0, 5.0, ["Ring"])])

    report = import_tagged(data_dir, src, mode="route", category="car", dry_run=True)

    assert report.rows
    assert not CountryPaths(data_dir, "AA").tagged_metas.exists()
    assert not CountryPaths(data_dir, "AA").geo.exists()


def test_untagged_and_unplaced_points_are_counted(data_dir, tmp_path):
    src = _source(tmp_path, [
        _point(5.0, 5.0, ["Ring"]),
        _point(5.0, 5.1, []),          # sans tag
        _point(5.0, 15.0, ["Ring"]),   # à > 10 km de tout pays
    ])

    report = import_tagged(data_dir, src, mode="route", category="car")

    assert report.untagged == 1
    assert report.unplaced == 1


def test_an_unreadable_file_fails_frankly(data_dir, tmp_path):
    f = tmp_path / "vide.json"
    f.write_text(json.dumps({"name": "x"}), "utf-8")
    with pytest.raises(TaggedFileError):
        import_tagged(data_dir, f, mode="route", category="car")


def test_zone_mode_uses_the_hull(data_dir, tmp_path):
    # Quatre coins d'un carré de ~30 km : une seule zone, pas quatre pastilles.
    src = _source(tmp_path, [
        _point(5.0, 5.0, ["Hut"]), _point(5.27, 5.0, ["Hut"]),
        _point(5.0, 5.27, ["Hut"]), _point(5.27, 5.27, ["Hut"]),
    ])

    import_tagged(data_dir, src, mode="zone", category="architecture")

    records = load_geo(CountryPaths(data_dir, "AA"))
    (record,) = records.values()
    assert len(record.pieces) == 1
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `uv run python -m pytest tests/test_tagged_importer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.tagged.importer'`.

- [ ] **Step 3: Implémenter**

Dans `cartometa/models.py`, à côté des autres origines :

```python
ORIGIN_TAGGED = "tagged"
```

Dans `cartometa/review/store.py`, ajouter à `CountryPaths` (après `rmrg_metas`) :

```python
    @property
    def tagged_metas(self) -> Path:
        return self.data / "metas" / f"{self.country}-tagged.json"
```

et étendre `load_metas` :

```python
def load_metas(paths: CountryPaths) -> list[dict]:
    """Imported metas (Plonk It, RMRG, tagged imports) then manual ones, in that order."""
    return (
        read_json_list(paths.imported_metas)
        + read_json_list(paths.rmrg_metas)
        + read_json_list(paths.tagged_metas)
        + read_json_list(paths.manual_metas)
    )
```

Créer `cartometa/tagged/importer.py` :

```python
from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cartometa.atomic_write import write_json_atomic
from cartometa.models import (
    ORIGIN_TAGGED,
    STATUS_PROPOSED,
    STATUSES,
    TIER_MANUAL,
    GeoRecord,
)
from cartometa.review.store import CountryPaths, load_geo, read_json_list, save_geo
from cartometa.tagged.countries import CountryIndex
from cartometa.tagged.geometry import corridor_geometry, geometry_to_pieces, zone_geometry

# Pre-simplification of the generated footprints, in degrees: ~50 m keeps a
# 500 m ribbon faithful, ~500 m is plenty for hulls inflated by 10 km.
SIMPLIFY_DEG = {"route": 0.0005, "zone": 0.005}
DEFAULT_LINK_KM = {"route": 5.0, "zone": 40.0}
REVIEW_PORT = 8799


class TaggedFileError(ValueError):
    """Import refused: unreadable input, active review session, or id collision."""


@dataclass
class TagReport:
    tag: str
    country: str
    points: int
    pieces: int
    action: str


@dataclass
class ImportReport:
    source: str
    mode: str
    untagged: int = 0
    unplaced: int = 0
    rows: list[TagReport] = field(default_factory=list)


def proposal_id(name: str, tag: str, country: str) -> str:
    """Deterministic id: re-runs regenerate the same records instead of duplicating.

    The `tag-` prefix keeps it apart from `man-` (4 hex) and from Plonk It ids
    (4 chars, no prefix); 6 hex keep the collision odds negligible at the scale
    of a few dozen metas per file — and a collision fails frankly (cf. caller).
    """
    digest = hashlib.sha1(f"{name}|{tag}|{country}".encode("utf-8")).hexdigest()
    return f"tag-{digest[:6]}"


def parse_tagged_file(path: Path) -> tuple[str, list[tuple[float, float, list[str]]]]:
    """(logical name, [(lat, lng, tags), ...]) — tags may be empty, caller counts."""
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaggedFileError(f"{path}: unreadable JSON ({exc})") from None
    coords = data.get("customCoordinates") if isinstance(data, dict) else None
    if not isinstance(coords, list) or not coords:
        raise TaggedFileError(f"{path}: no customCoordinates list")
    name = data.get("name") or path.stem
    points = []
    for entry in coords:
        try:
            lat, lng = float(entry["lat"]), float(entry["lng"])
        except (KeyError, TypeError, ValueError):
            raise TaggedFileError(f"{path}: point without usable lat/lng: {entry!r}") from None
        tags = entry.get("extra", {}).get("tags") or []
        points.append((lat, lng, [str(t) for t in tags]))
    return name, points


def _review_running(port: int = REVIEW_PORT) -> bool:
    # The review server rewrites data/geo as decisions land: importing under it
    # would interleave two writers on the same files. Detection is best-effort
    # (a session on a custom --port slips through) but catches the normal case.
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _build_geometry(points, mode, buffer_m, link_km, hull_buffer_km):
    if mode == "route":
        return corridor_geometry(points, buffer_m=buffer_m, link_km=link_km)
    return zone_geometry(points, hull_buffer_km=hull_buffer_km, link_km=link_km)


def import_tagged(
    data_dir: Path,
    file: Path,
    *,
    mode: str,
    category: str,
    buffer_m: float = 250.0,
    link_km: float | None = None,
    hull_buffer_km: float = 10.0,
    dry_run: bool = False,
) -> ImportReport:
    if mode not in SIMPLIFY_DEG:
        raise TaggedFileError(f"unknown mode: {mode!r} (expected route or zone)")
    if not dry_run and _review_running():
        raise TaggedFileError(
            "a cartometa-review session seems active (port 8799 answers): "
            "both write data/geo — stop it before importing."
        )
    link = DEFAULT_LINK_KM[mode] if link_km is None else link_km
    name, raw_points = parse_tagged_file(file)
    report = ImportReport(source=name, mode=mode)

    index = CountryIndex(data_dir / "cache")
    groups: dict[tuple[str, str], list[tuple[float, float]]] = {}
    placement: dict[tuple[float, float], str | None] = {}
    for lat, lng, tags in raw_points:
        if not tags:
            report.untagged += 1
            continue
        key = (lat, lng)
        if key not in placement:
            placement[key] = index.country_of(lat, lng)
        country = placement[key]
        if country is None:
            report.unplaced += 1
            continue
        for tag in tags:
            groups.setdefault((tag, country), []).append((lat, lng))

    by_country: dict[str, list[tuple[str, str, list, list[dict]]]] = {}
    seen_ids: dict[str, tuple[str, str]] = {}
    for (tag, country), points in sorted(groups.items()):
        pid = proposal_id(name, tag, country)
        if pid in seen_ids:
            raise TaggedFileError(
                f"id collision: {seen_ids[pid]} and {(tag, country)} both give {pid}"
            )
        seen_ids[pid] = (tag, country)
        geom = _build_geometry(points, mode, buffer_m, link, hull_buffer_km)
        pieces = geometry_to_pieces(geom, SIMPLIFY_DEG[mode])
        by_country.setdefault(country, []).append((pid, tag, points, pieces))

    now = datetime.now(timezone.utc).isoformat()
    for country, proposals in sorted(by_country.items()):
        paths = CountryPaths(data_dir, country)
        records = load_geo(paths)
        metas = {m["id"]: m for m in read_json_list(paths.tagged_metas)}
        touched = False
        for pid, tag, points, pieces in proposals:
            existing = records.get(pid)
            if existing is not None and existing.status in STATUSES:
                report.rows.append(TagReport(tag, country, len(points), len(pieces),
                                             "sautée (décidée)"))
                continue
            meta = {
                "id": pid, "country": country, "tier": TIER_MANUAL,
                "title": tag, "description": tag, "category": category,
                "source_url": "",
                # Kept across re-runs: two identical runs must be byte-identical.
                "extracted_at": metas.get(pid, {}).get("extracted_at", now),
                "description_origin": "imported", "origin": ORIGIN_TAGGED,
                "image": None, "maps_url": None, "maps_latlon": None,
                "source_file": name, "source_tag": tag,
            }
            record = GeoRecord(id=pid, geometry=None, pieces=pieces,
                               status=STATUS_PROPOSED)
            if existing is None:
                action = "écrite"
            elif metas.get(pid) == meta and _same_pieces(existing.pieces, pieces):
                action = "inchangée"
            else:
                action = "réécrite"
            report.rows.append(TagReport(tag, country, len(points), len(pieces), action))
            if action != "inchangée":
                touched = True
            metas[pid] = meta
            records[pid] = record
        if not dry_run and touched:
            paths.tagged_metas.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(paths.tagged_metas,
                              [metas[k] for k in sorted(metas)])
            save_geo(paths, records)
    return report


def _same_pieces(stored: list[dict], generated: list[dict]) -> bool:
    """Stored pieces went through save_geo's 5-decimal rounding: compare in
    that space, not raw floats against rounded ones."""
    def _round(value):
        if isinstance(value, float):
            return round(value, 5)
        if isinstance(value, list):
            return [_round(v) for v in value]
        if isinstance(value, dict):
            return {k: _round(v) for k, v in value.items()}
        return value

    return _round(stored) == _round(generated)
```

Attention au piège de l'idempotence : les pièces relues du disque sont arrondies à 5 décimales par `save_geo`, celles qu'on vient de générer non — d'où `_same_pieces` qui compare dans l'espace arrondi. Si `test_rerunning_the_import_changes_nothing` échoue sur des octets différents, chercher d'abord de ce côté.

- [ ] **Step 4: Vérifier que tout passe**

Run: `uv run python -m pytest tests/test_tagged_importer.py tests/test_store.py -v`
Expected: PASS (dont les tests existants de `load_metas`, insensibles au fichier tagged absent).

- [ ] **Step 5: Commit**

```bash
git add cartometa/models.py cartometa/review/store.py cartometa/tagged/importer.py tests/test_tagged_importer.py
git commit -m "feat: importeur de JSON taggés — metas et empreintes proposées"
```

---

### Task 8: La commande `cartometa-import-tagged`

**Files:**
- Create: `cartometa/tagged/cli.py`
- Modify: `pyproject.toml:18-22` (`[project.scripts]`)
- Test: `tests/test_tagged_cli.py`

**Interfaces:**
- Consumes: `import_tagged`, `ImportReport`, `TaggedFileError` (tâche 7) ; `CATEGORIES` (`cartometa.extract.categories`).
- Produces: le point d'entrée `cartometa-import-tagged = "cartometa.tagged.cli:main"` ; `main(argv: list[str] | None = None) -> None`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_tagged_cli.py` (réutiliser à l'identique les fixtures `data_dir` et `_source`/`_point` de `tests/test_tagged_importer.py` — les copier, chaque fichier de test reste autonome) :

```python
import json

import pytest

from cartometa.geo.reference import DATASET_NAME
from cartometa.review.store import CountryPaths
from cartometa.tagged.cli import main


def _point(lat, lng, tags):
    return {"lat": lat, "lng": lng, "extra": {"tags": tags}}


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    (d / "cache").mkdir(parents=True)
    (d / "cache" / DATASET_NAME).write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"ISO_A2": "AA", "ISO_A2_EH": "AA"},
             "geometry": {"type": "Polygon", "coordinates": [[
                 [0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0],
             ]]}},
        ],
    }), "utf-8")
    return d


def _source(tmp_path):
    f = tmp_path / "source.json"
    f.write_text(json.dumps({"name": "fichier test", "customCoordinates": [
        _point(5.0, 5.0, ["Ring"]), _point(5.01, 5.01, ["Ring"]),
    ]}), "utf-8")
    return f


def test_the_cli_imports_and_prints_the_recap(data_dir, tmp_path, capsys):
    main([str(_source(tmp_path)), "--mode", "route", "--category", "car",
          "--data-dir", str(data_dir)])

    out = capsys.readouterr().out
    assert "Ring" in out and "AA" in out
    assert CountryPaths(data_dir, "AA").geo.exists()


def test_an_unknown_category_is_refused(data_dir, tmp_path):
    with pytest.raises(SystemExit):
        main([str(_source(tmp_path)), "--mode", "route", "--category", "bidon",
              "--data-dir", str(data_dir)])


def test_dry_run_prints_but_writes_nothing(data_dir, tmp_path, capsys):
    main([str(_source(tmp_path)), "--mode", "route", "--category", "car",
          "--data-dir", str(data_dir), "--dry-run"])

    assert "Ring" in capsys.readouterr().out
    assert not CountryPaths(data_dir, "AA").geo.exists()
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `uv run python -m pytest tests/test_tagged_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cartometa.tagged.cli'`.

- [ ] **Step 3: Implémenter**

Créer `cartometa/tagged/cli.py` :

```python
from __future__ import annotations

import argparse
from pathlib import Path

from cartometa.extract.categories import CATEGORIES
from cartometa.tagged.importer import ImportReport, TaggedFileError, import_tagged


def _print_report(report: ImportReport, dry_run: bool) -> None:
    dropped = ""
    if report.untagged or report.unplaced:
        dropped = (f", {report.untagged} sans tag, "
                   f"{report.unplaced} hors de tout pays")
    header = f"{report.source} — mode {report.mode}{dropped}"
    if dry_run:
        header += "  [dry-run : rien n'est écrit]"
    print(header)
    for row in sorted(report.rows, key=lambda r: (r.tag, r.country)):
        print(f"  {row.tag:40s} {row.country}  {row.points:5d} pts "
              f"-> {row.pieces:3d} pièce(s)   {row.action}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="cartometa-import-tagged",
        description="Transforme un JSON de points taggés (format carte GeoGuessr) "
                    "en metas proposées, à valider dans cartometa-review.",
    )
    parser.add_argument("file", type=Path, help="le JSON de points taggés")
    parser.add_argument("--mode", required=True, choices=("route", "zone"),
                        help="corridor fidèle (route) ou enveloppe concave (zone)")
    parser.add_argument("--category", required=True,
                        help=f"catégorie des metas produites ({', '.join(CATEGORIES)})")
    parser.add_argument("--buffer-m", type=float, default=250.0,
                        help="demi-largeur du corridor en mètres (défaut 250)")
    parser.add_argument("--link-km", type=float, default=None,
                        help="seuil de chaînage en km (défaut 5 en route, 40 en zone)")
    parser.add_argument("--hull-buffer-km", type=float, default=10.0,
                        help="gonflement de l'enveloppe en km (défaut 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="calcule et affiche le récapitulatif sans rien écrire")
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.category not in CATEGORIES:
        parser.error(f"unknown category: {args.category!r} "
                     f"(expected {', '.join(CATEGORIES)})")
    try:
        report = import_tagged(
            args.data_dir, args.file, mode=args.mode, category=args.category,
            buffer_m=args.buffer_m, link_km=args.link_km,
            hull_buffer_km=args.hull_buffer_km, dry_run=args.dry_run,
        )
    except TaggedFileError as exc:
        raise SystemExit(str(exc)) from None
    _print_report(report, args.dry_run)


if __name__ == "__main__":
    main()
```

Dans `pyproject.toml`, section `[project.scripts]`, ajouter :

```toml
cartometa-import-tagged = "cartometa.tagged.cli:main"
```

- [ ] **Step 4: Vérifier que tout passe**

Run: `uv run python -m pytest tests/test_tagged_cli.py -v` puis `uv run python -m pytest`
Expected: PASS partout (la suite complète tourne pour attraper une régression transverse).

- [ ] **Step 5: Commit**

```bash
git add cartometa/tagged/cli.py pyproject.toml uv.lock tests/test_tagged_cli.py
git commit -m "feat: commande cartometa-import-tagged"
```

(Si `uv.lock` n'a pas bougé, ne pas l'ajouter.)

---

### Task 9: Bout en bout sur les fichiers réels

**Files:**
- Aucune création — exécution, vérification visuelle, corrections éventuelles.

**Interfaces:**
- Consumes: tout ce qui précède, plus les fichiers réels `input/Architecture.json` (zones, Pologne) et `input/ua antennas.json` (routes, Ukraine).

Rappels d'environnement : Anki occupe le port 8765 et répond à la place du serveur de revue si on le laisse s'y lier — le défaut 8799 est le bon. Ne jamais lancer deux builds en parallèle. Le serveur de revue réécrit `data/geo/` en continu : pas d'import ni de commande git pendant qu'une session tourne.

- [ ] **Step 1: Dry-run sur les deux fichiers réels**

```bash
uv run cartometa-import-tagged "input/Architecture.json" --mode zone --category architecture --dry-run
uv run cartometa-import-tagged "input/ua antennas.json" --mode route --category car --dry-run
```

Expected : ~14 lignes (Architecture, quasi tout PL) et ~19 lignes × pays (ua antennas, quasi tout UA) ; quelques points frontaliers chez les voisins sont normaux et attendus. Vérifier que les comptes de points par tag collent aux totaux connus (479 « Attic Windows - Horizontal », 2 592 « June »…). Chronométrer : si « June » (2 592 points) dépasse ~2 minutes, le MST a un problème de complexité.

- [ ] **Step 2: Import réel et inspection des fichiers**

```bash
uv run cartometa-import-tagged "input/Architecture.json" --mode zone --category architecture
uv run cartometa-import-tagged "input/ua antennas.json" --mode route --category car
git diff --stat data/geo/
```

Expected : `data/metas/PL-tagged.json`, `data/metas/UA-tagged.json` (et voisins éventuels) créés ; `data/geo/PL.geojson` et `data/geo/UA.geojson` grossis mais dans des proportions tenables (< ~10 Mo chacun). Relancer chaque commande une seconde fois : `git status` ne doit montrer **aucun** nouveau changement (idempotence sur données réelles).

- [ ] **Step 3: La revue, visuellement**

```bash
uv run cartometa-review UA
```

Ouvrir `http://127.0.0.1:8799` et vérifier : les metas proposées sont dans la file avec le contexte `car — manual — proposé` ; la carte se cadre sur le corridor, pas sur l'Ukraine entière ; le ruban est fin (500 m) et suit visiblement des routes ; `A` valide (statut `validé` dans le geojson), `U` restaure `proposé` avec ses pièces, `R` rejette. Refaire le même contrôle rapide sur `PL` (enveloppes concaves). Piloter en CDP si besoin (voir la note mémoire « Piloter le viewer en CDP »). Arrêter le serveur avant l'étape suivante.

- [ ] **Step 4: Le build n'exporte rien de proposé**

```bash
uv run cartometa-build UA
python -c "
import json, pathlib
for f in pathlib.Path('dist').rglob('UA.json'):
    data = json.loads(f.read_text('utf-8'))
    ids = [i for i in data.get('metas', {}) if i.startswith('tag-')]
    print(f, len(ids), 'meta(s) tag- publiée(s)')
"
```

Expected : 0 meta `tag-` publiée tant qu'aucune n'a été validée à l'étape 3 — si une l'a été, elle doit être exactement le compte validé. Aucun avertissement « legacy status » dans la sortie du build.

- [ ] **Step 5: Suite complète et commit final**

```bash
uv run python -m pytest
git add data/geo/PL.geojson data/geo/UA.geojson
git status
```

`git status` doit être propre hors `data/geo/*.geojson` (les `data/metas/*-tagged.json` sont gitignorés d'office). Ne committer les geojson que si le résultat visuel de l'étape 3 était satisfaisant :

```bash
git commit -m "feat: empreintes proposées depuis Architecture.json et ua antennas.json"
```

Sinon, noter ce qui cloche (seuils, buffers, enveloppes) et ajuster via les options CLI avant de recommencer — `git restore data/geo` remet à zéro tant que rien n'est validé.
