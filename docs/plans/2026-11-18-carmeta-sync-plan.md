# cartometa-carmeta — plan d'implémentation

**Spec :** `docs/specs/2026-11-18-carmeta-sync-design.md` (à lire en entier avant
de commencer ; les § cités ci-dessous y renvoient).
**Prototype de référence :** `docs/specs/2026-11-18-carmeta-spike/` — `zones.py`
fait foi sur les détails d'algorithme, `expected-verdicts.json` sur les
résultats attendus.

**But :** un module `cartometa/carmeta/` et une commande `cartometa-carmeta`
(`sync`, `status`, `arbitrate`, `import`) qui transforment les JSON du repo
carmeta en metas `car` proposées, à valider dans `cartometa-review`.

**Découpage :** 22 tâches en 5 phases. Chaque tâche = tests d'abord, code,
suite complète verte, un commit. Les cases se cochent au fur et à mesure.
**Un seul arrêt prévu** : la revue du Mexique par le mainteneur après la
tâche 16 (critère de succès 1), avant tout import de masse.

| Phase | Tâches | Livre |
|---|---|---|
| A. Calcul pur | 1–5 | règles, familles, zones, gain, empreinte, pays — sans réseau ni disque |
| B. Analyse | 6–11 | miroir du repo, analyse par pays, verdicts, `sync` minimal, contrôle sur données réelles |
| C. Import et revue | 12–16 | metas proposées, re-propositions, interface de revue → **arrêt Mexique** |
| D. Arbitrage, rapport, planification | 17–19 | `arbitrate`, `report.html`, `status`, tâche planifiée |
| E. Publication | 20–22 | build, viewer, licence, docs, bout en bout |

---

## 1. Contraintes globales

- Tests : `uv run python -m pytest` (jamais `uv run pytest`). Réseau **toujours**
  simulé (fonction `fetch` injectée), nuages de points synthétiques, `tmp_path`.
- Une seule dépendance ajoutée : `numpy` (déjà dans `uv.lock` via shapely).
  Ni scipy, ni requests, ni rasterio.
- Branche dédiée `carmeta-sync` tirée de `master` (pas `metas-np`). Le premier
  commit embarque la spec, le prototype et ce plan, aujourd'hui non suivis.
- Statuts et verdicts gardent leur graphie : `validé`, `rejeté`, `proposé` ;
  `retenu`, `arbitrage`, `écarté` et les motifs **mot pour mot** ceux de
  `expected-verdicts.json`.
- Code, docstrings et noms de tests en anglais, comme le reste du dépôt. Sortie
  console et rapport en français (comme `cartometa-import-tagged`), sans tiret
  cadratin ni caractère de boîte dans la console (cp1252 sous Windows). Titres
  et descriptions des metas en anglais.
- `sync` n'écrit **que** sous `data/cache/carmeta/` et `logs/`. Un test le
  vérifie par instantané de l'arborescence.
- Écritures versionnées par `write_json_atomic`, clés triées : deux exécutions
  identiques donnent des fichiers identiques octet pour octet.
- Requêtes sortantes : `User-Agent: carmeta-sync`, rien d'autre que le chemin
  demandé. `GITHUB_TOKEN` seulement s'il est défini.
- Style : commentaires sobres qui expliquent la contrainte, à la manière de
  `cartometa/review/store.py`.

## 2. Décisions d'implémentation

La spec laisse ces points ouverts ou ambigus ; ils sont tranchés ici pour que
l'implémentation ne s'arrête pas. Chacun est réversible sans toucher aux
données validées.

| # | Sujet | Décision |
|---|---|---|
| D1 | Clés du lexique | Descripteurs **normalisés** (sans `Car`, sans `Antenna`, `Grey`→`Gray`, espaces réduits). `No Car` est l'exception : conservé tel quel. Recherche insensible à la casse, la graphie du lexique fait foi. L'annexe B est passée par le normaliseur à l'amorçage (`Alberta Car` → `Alberta`). |
| D2 | Portée du lexique | Tout tag gardé sauf `copyright` a une clé de lexique : le descripteur pour `car_year`/`car`, la forme canonique pour `antenna`, `bl`, `blur`, `exposed`, `snow`, `smallcam`. Clé absente ou `pending` → arbitrage « descripteur inconnu ». C'est ce qui rend cohérent `New Blur` en attente (annexe B) alors que §8.1 garde la famille `blur`. |
| D3 | `car` contre `unknown` | Tag sans année qui n'entre dans aucune famille fixe : `car` si sa forme normalisée est une clé du lexique, `unknown` sinon. Un `unknown` accepté en arbitrage entre au lexique, donc devient `car`. |
| D4 | Statuts du lexique | `accepted` (avec `label`), `pending`, `rejected`. `arbitrate` : *keep* → `accepted` + libellé demandé ; *drop* → `rejected` (tag écarté, jamais redemandé). |
| D5 | Portée d'une décision | Une décision `<CC>|<canonique>` non périmée remplace les trois lignes de gain du §9.4 (`< 10 %`, `< 20 %`, `sinon`). Périmée = le gain s'est écarté de plus de 0,10 du gain enregistré : le tag repasse en `arbitrage` (« décision à revoir ») **où que soit le gain**. La bande 10–20 % ne fait que 10 points : une décision périmée en est forcément sortie, et rendre la main au verdict calculé importerait sans rien demander un tag que le mainteneur avait écarté. |
| D6 | Ce qui est figé dans l'analyse | L'analyse en cache porte les mesures et le verdict **géométrique** (seuils + sources). Décisions et lexique sont appliqués **à la lecture** (`effective_verdict`) : `arbitrate` puis `import` s'enchaînent sans `sync`. L'analyse stocke une empreinte des seuils et des sources ; si elle ne correspond plus à `rules.json`, `import` et `arbitrate` refusent et renvoient à `sync --force`. |
| D7 | Empreintes calculées pour qui | Tout tag qui atteint les lignes de gain (≥ 30 points, non parent, au moins une zone, capture ≥ 35 %), y compris les « non discriminants » : une décision *keep* doit pouvoir s'importer sans recalcul. Environ 660 tags aujourd'hui. |
| D8 | Choix de source | La règle 3 du §7 s'applique telle quelle à **chaque** famille gardée, `car` et `unknown` compris. `sources.exclude` : liste de chemins jamais utilisés. `sources.pin` : `{"AU": chemin}` (toutes familles) ou `{"AU|copyright": chemin}` (une famille). |
| D9 | Fermeture morphologique | Sur le masque **réuni** des zones du tag (pas zone par zone), rogné à leur boîte englobante. Les quatre réglages du §11 sont des constantes en tête de `footprint.py`, ajustées à l'arrêt Mexique. |
| D10 | Référence d'empreinte (`baseline`) | Union des pièces `polygon` **avant** découpe aux frontières, arrondie à 5 décimales, en GeoJSON `MultiPolygon`. Le recouvrement se calcule en lon/lat : un rapport d'aires est invariant par l'échelle locale. |
| D11 | Textes d'une meta validée | Empreinte stable (recouvrement ≥ 80 %) : le bloc `carmeta` n'est pas touché, mais titre et description sont régénérés depuis ses chiffres **stockés** et le lexique courant. Sans cela une correction de libellé (§3 : « ils se corrigent dans le lexique ») n'atteindrait jamais une meta validée. |
| D12 | `R` sur une re-proposition | Garde-fou **côté serveur** : un rejet reçu pour une meta `validé` qui porte une `proposal` efface la `proposal` et rien d'autre. Le client ne peut pas dépublier par erreur. |
| D13 | Tag disparu, cas non couverts | Meta `rejeté` : conservée (texte et rejet), sinon le rejet ne serait pas définitif. Meta `validé` avec `proposal` : la `proposal` est retirée. Pays avec des metas carmeta mais **sans fichier d'analyse** : ignoré avec un avertissement — l'absence d'analyse n'est pas une preuve. Un pays que plus aucun fichier ne sert reçoit une analyse **vide**, qui, elle, en est une. |
| D14 | « Aucun changement » | `sync` compare le sha de l'arbre racine avant de prendre le verrou : identique et rien en attente → sortie sans la moindre écriture. Un passage interrompu laisse la liste `dirty` dans `state.json`, qui force l'analyse au passage suivant. |
| D15 | Cache compact | Un `files/<sha>.npz` par fichier : `lat`, `lng`, `heading`, `pano`, `combo` (indice de combinaison de tags), `country` (indice de pays, calculé une fois), plus un JSON embarqué (nom, tags, combinaisons, couleurs, ordres). Les JSON bruts ne sont pas gardés. |
| D16 | Lien Street View en revue | Ajout hors spec, minime : la revue affiche un lien « Street View » quand la meta a un `maps_url`. Sans image, c'est le seul moyen de voir l'indice avant de valider. |
| D17 | Orphelins `car-` au build | Fatals, comme `man-` : `data/carmeta/` est versionné, un texte manquant est une perte. |
| D18 | Couleur du tag | Rangée dans `carmeta.color` (`#rrggbb`) ; pour des tags fusionnés, celle du tag brut le plus fourni. Format source à vérifier sur un fichier réel (tâche 7) ; illisible → absente. |
| D19 | Inclinaison du lien | Clé optionnelle `streetview_pitch` dans `rules.json`, défaut −35. |
| D20 | `Black 2025` et `Black 2025 (A+NA)` | Deux formes canoniques, donc deux identifiants, même titre. Si les deux existent dans un pays, le mainteneur en rejette une en revue. |
| D21 | Suppression d'un coverage disparu | Demande du mainteneur (2026-11-18). Une meta `validé` dont le tag a disparu reste publiée par défaut ; `cartometa-carmeta prune [CC …] [--yes]` la supprime (texte et empreinte) après confirmation. Suppression et non rejet : un tag qui réapparaît est re-proposé. |

## 3. Architecture

```
cartometa/carmeta/
  paths.py      CarmetaPaths : tous les chemins du §5 en un seul endroit
  rules.py      Rules : lecture/écriture de rules.json, valeurs par défaut, empreinte des règles
  tags.py       familles, forme canonique, normalisation des descripteurs
  zones.py      repère local, D, δ, zones, gain régional (numpy pur)
  footprint.py  zones → raster → fermeture → polygones → pièces ; recouvrement
  countries.py  point → pays, vectorisé
  github.py     arbre du repo, date de commit, téléchargement brut (fetch injectable)
  mirror.py     state.json, diff, décodage zip/JSON, cache compact
  analysis.py   analyse (fichier, pays), choix des sources, analysis/<CC>.json
  verdicts.py   verdict géométrique, verdict effectif, cas en attente
  texts.py      identifiant, titre, description, lien Street View
  importer.py   plan_import (lecture seule) + apply_import
  arbitrate.py  boucle interactive
  report.py     report.html et résumé texte
  sync.py       orchestration, verrou, journal, notification
  cli.py        cartometa-carmeta <sous-commande>
```

Le socle n'est touché qu'en six endroits : `models.py` (origine, `proposal`),
`review/store.py` (source de metas, file, re-propositions), `review/server.py`
et `review/static/` (revue), `build/dataset.py`, `viewer/`.

### Formats du cache (`data/cache/carmeta/`)

`state.json` :

```json
{"tree_sha": "…", "checked_at": "…", "dirty": ["MX"],
 "files": {"NorthAmerica/Mexico/Mexico 12_23_25.json": {
   "sha": "…", "commit_date": "2026-05-06T13:05:16Z", "fetched_at": "…",
   "kind": "points", "name": "…", "points": 152340,
   "countries": {"MX": 151900, "US": 440}}}}
```

`kind` vaut `points` ou `other` (blob téléchargé qui n'est pas un fichier de
points : on ne le retélécharge pas tant que son sha ne bouge pas).

`analysis/<CC>.json` (aucun horodatage dedans : sortie déterministe) :

```json
{"country": "MX", "rules_fingerprint": "…",
 "sources": [{"path": "…", "sha": "…", "date": "…", "role": "primary",
              "points": 151900, "families": ["car_year"],
              "grid": {"s": 20.1, "W": 96, "H": 71, "D": 1206.0, "R": 120.6,
                       "delta": 0.9, "link": 2.7, "cov": "<base64>"}}],
 "rows": [{"canonical": "Blue Unexposed 2024", "family": "car_year",
           "lexicon_key": "Blue Unexposed", "year": 2024, "antenna": null,
           "raw_tags": ["Blue Unexposed 2024"], "source": 0, "color": "#3366cc",
           "points": 13750, "zones": 45, "capture": 0.90, "gain": 0.42,
           "verdict": "retenu", "reason": "",
           "rep": {"lat": 19.4, "lng": -99.1, "pano": "…", "heading": 271.5},
           "pieces": [{"kind": "polygon", "ring": []}, {"kind": "clip"}],
           "cells": "<base64 : zone / éliminée / couverte, pour la carte du rapport>"}],
 "unused_paths": []}
```

`pieces` et `rep` sont `null` pour un tag qui n'atteint pas les lignes de gain.
`pending.json` : la liste des cas en attente produite par `pending_cases`.

---

## Phase A — Calcul pur

### Tâche 1 : ossature, règles, fichier `rules.json` initial

**Fichiers :** `pyproject.toml`, `cartometa/carmeta/{__init__,paths,rules}.py`,
`data/carmeta/rules.json`, `tests/test_carmeta_rules.py`.

- [x] `pyproject.toml` : ajouter `numpy` aux dépendances, le script
      `cartometa-carmeta = "cartometa.carmeta.cli:main"`, le marqueur pytest
      `carmeta_cache: requires data/cache/carmeta/analysis/, skipped if absent`.
      `uv lock` ne doit changer que la liste des dépendances directes.
- [x] `CarmetaPaths(data: Path)` : `cache`, `files`, `state`, `analysis_dir`,
      `analysis(cc)`, `report`, `pending`, `lock`, `rules`, `metas(cc)`.
- [x] `Rules` (dataclasses) : `thresholds` (`min_zone_points`, `min_capture`,
      `gain_drop`, `gain_keep`, `reproposal_iou`), `pin`, `exclude`, `lexicon`
      (`label`, `status`), `decisions` (`decision`, `gain`, `decided_at`),
      `streetview_pitch`. `load_rules(path)` : fichier absent → valeurs par
      défaut du §10 ; clé inconnue ou statut invalide → erreur qui nomme la clé.
      `save_rules` : atomique, clés triées. `analysis_fingerprint(rules)` : sha1
      des seuils (hors `reproposal_iou`) et de `sources`.
- [x] Écrire `data/carmeta/rules.json` : seuils du §10, lexique de l'annexe B
      passé par le normaliseur (D1), plus `Antenna`, `Snow`, `BL`, `Front Blur`,
      `Exposed`, `Exposed Back` acceptés (D2). Libellés anglais d'après la table
      du §12 (`Blue` → `Blue car`, `No Car` → `No car visible`, `BL` → `Brake
      light`…).

**Tests :** aller-retour octet pour octet ; défauts quand le fichier manque ;
l'empreinte change avec un seuil ou un épinglage, pas avec une décision ni une
entrée de lexique ; le `rules.json` versionné se charge.

### Tâche 2 : familles et forme canonique (§8.1, §8.2)

**Fichiers :** `cartometa/carmeta/tags.py`, `tests/test_carmeta_tags.py`.

```python
KEPT_FAMILIES = ("car_year", "car", "copyright", "antenna", "bl", "blur",
                 "exposed", "snow", "smallcam", "unknown")

@dataclass(frozen=True)
class Canonical:
    family: str
    text: str                  # "Blue 2024 (NA)", "©2025", "BL"
    lexicon_key: str | None    # None for copyright
    year: int | None = None
    antenna: str | None = None # "A", "NA", "A+NA"

def classify(tag: str, iso_codes: frozenset[str], lexicon: Mapping) -> Canonical | None
def normalize_descriptor(descriptor: str) -> str
```

- [x] `classify` rend `None` pour une famille écartée. Ordre d'évaluation **du
      tableau §8.1** (`bl` avant `country`), repris de `family()` du prototype.
- [x] `car_year` : `<descripteur> <année>` + suffixe optionnel ; année sur 2
      chiffres → `20xx` ; `Antenna` dans le descripteur → antenne `A` ; `BL` et
      `Brakelight` → `BL` ; `© 2025` → `©2025`.
- [x] `normalize_descriptor` selon D1.

**Tests :** une table paramétrée tirée du vocabulaire réel — au minimum :
`Blue 24 (NA)`, `Blue 2024 (NA)`, `Blue Car 2024`, `Blue Car Antenna 2024`,
`Grey 2023`, `No Car 2023`, `Smallcam 25`, `Black 2025 (A+NA)`, `©2026`, `BL`,
`Brakelight`, `No BL`, `No Antenna`, `DE`, `Bayern`, `Csa`, `ET`, `P2`,
`Part 3`, `Gen 4`, `Normal Gen 4`, `2024`, `7`, `24-06`, `Overcast`,
`───Month───`, `Antenna`, `Snow`, `Front Blur`, `New Blur`, `Exposed Back`,
`Black` (→ `car`), `Truck` (→ `car`, clé `pending`), `Zorglub` (→ `unknown`).

### Tâche 3 : repère, zones et gain (§9.1–9.3)

**Fichiers :** `cartometa/carmeta/zones.py`, `tests/test_carmeta_zones.py`.

```python
@dataclass
class Frame:       # one per (source file, country)
    x: np.ndarray; y: np.ndarray        # km, local projection
    lat0: float; kx: float; wrapped: bool   # wrapped: +360 applied to negative lngs
    D: float; delta: float; link: float     # link = L = max(3·delta, 1 km)
    s: float; W: int; H: int; x0: float; y0: float
    flat: np.ndarray; tot: np.ndarray       # analysis cell per point, points per cell

def build_frame(lat, lng) -> Frame
def tag_zones(frame, members, min_zone_points) -> Zones   # labels, sizes, capture, cells
def regional_gain(frame, zone_points, min_known=30) -> float
def representative(frame, zones) -> int   # point of the largest zone nearest its centre
def to_wgs(frame, geometry) -> BaseGeometry
```

- [x] Port fidèle de `analyse_country` du prototype, découpé en fonctions
      testables : projection et antiméridien, `D` (enveloppe convexe,
      échantillon de 20 000 points), `δ` (300 points, `default_rng(0)`),
      grille de hachage `L`, composantes 8-voisines, `capture`.
- [x] Gain : `R = 0,10·D` uniquement (les variantes `G3`/`G6` du prototype
      disparaissent), `s = D/60` borné entre 1,5 et 25 km, cases connues
      `tot > 0` et `totR ≥ 30`.

**Tests (ceux du §17) :** chaîne de 30 points espacés de `δ` → une zone, 29 →
aucune, points isolés ignorés ; gain d'un tag uniforme ≈ 0 ; confiné à une
moitié ≈ 0,50 ; présent sur 90 % ≈ 0,10 ; damier fin ≈ 0 (tolérance ±0,06 :
le lissage à l'échelle `R` adoucit les bords) ; nuage à cheval sur
l'antiméridien ; déterminisme entre deux appels.

### Tâche 4 : empreinte (§11)

**Fichiers :** `cartometa/carmeta/footprint.py`, `tests/test_carmeta_footprint.py`.

```python
CLOSING_RADIUS_CELLS = 2
MAX_HOLE_CELLS = 25
DILATE_FACTOR = 0.5       # × L
SIMPLIFY_FACTOR = 0.25    # × L

def footprint_pieces(frame, zones) -> list[dict]   # polygon pieces + {"kind": "clip"}
def pieces_geometry(pieces) -> BaseGeometry        # union of the polygon pieces, unclipped
def iou(a: BaseGeometry, b: BaseGeometry) -> float
```

- [x] Masque des cases de zone sur la grille `L`, rogné à la boîte englobante
      plus une marge ; fermeture = dilatation puis érosion par un disque
      (`dilate_disc` du prototype) ; trous = composantes du fond qui ne touchent
      pas le bord, comblées sous 25 cases.
- [x] Polygonisation sans dépendance : fusionner chaque ligne du masque en
      rectangles (`shapely.box`), puis `unary_union`. Lissage : `buffer(L/2)`,
      `simplify(L/4)`.
- [x] Retour en WGS84 par `to_wgs` (longitudes ramenées dans ±180), puis
      `geometry_to_pieces` de `cartometa/tagged/geometry.py` (plafond
      `MAX_RING_POINTS`, trous), puis ajout de la pièce `clip`.

**Tests :** deux routes parallèles à 2 cases d'écart → un seul polygone ; à 8
cases → deux ; un trou de 10 cases comblé, un de 60 conservé ; tout point de
zone est dans l'empreinte ; `resolve_pieces` accepte le résultat et le découpe
au pays ; `iou` vaut 1 sur soi-même, 0 sur disjoints, 1/3 sur deux carrés
décalés d'une moitié.

### Tâche 5 : pays d'un point, vectorisé (§7)

**Fichiers :** `cartometa/carmeta/countries.py`, `tests/test_carmeta_countries.py`.

- [x] `CountryAssigner(cache_dir)` : `codes: list[str]`, `iso: frozenset[str]`,
      `assign(lat, lng) -> np.ndarray` (indice dans `codes`, −1 hors de tout
      pays). Port de `Countries` du prototype : préfiltre par boîtes,
      `shapely.contains_xy` sur géométries préparées, puis plus proche pays à
      moins de `NEAREST_MAX_DEG` (importé de `cartometa/tagged/countries.py`,
      pas recopié).
- [x] `CountryIndex` reste en place pour `cartometa-import-tagged`.

**Tests :** mêmes cas que `tests/test_tagged_countries.py` (dedans, au large à
0,05°, loin de tout, code `-99`), plus l'égalité avec `CountryIndex.country_of`
sur 500 points tirés au hasard.

---

## Phase B — Analyse

### Tâche 6 : miroir du repo (§6)

**Fichiers :** `cartometa/carmeta/{github,mirror}.py`,
`tests/test_carmeta_{github,mirror}.py`.

```python
Fetch = Callable[[str, dict[str, str]], bytes]     # url, headers -> body

def fetch_tree(fetch) -> Tree                  # root sha + [(path, blob sha, size)]
def commit_date(fetch, path) -> str            # ISO date of the path's last commit
def download(fetch, path, expected_sha) -> bytes
def diff(state, tree) -> Diff                  # new, modified, deleted paths
def decode_points(raw: bytes) -> PointsFile | None    # None: not a points file
def store_compact(paths, sha, points, country_idx) -> None
def load_compact(paths, sha) -> CompactFile
```

- [x] `github.py` : bibliothèque standard seulement. Chemins encodés
      (`urllib.parse.quote`), `User-Agent` générique, `Authorization` si
      `GITHUB_TOKEN`. `truncated: true` dans l'arbre → erreur explicite. 403 de
      quota → `RateLimited`, avec l'heure de réinitialisation si l'en-tête la
      donne. Le téléchargement vérifie le sha git du blob
      (`sha1(b"blob <taille>\0" + contenu)`) : un fichier modifié entre l'arbre
      et le téléchargement est laissé pour le passage suivant.
- [x] `decode_points` reconnaît le format **au contenu** : magie `PK` → premier
      membre hors `__MACOSX` ; sinon JSON avec `customCoordinates`. Un pointeur
      Git LFS (`version https://git-lfs…`) est signalé comme tel, pas pris pour
      un fichier vide. Points écartés à la lecture : sans `panoId`, ou
      latitude au-delà de ±84° (points factices des séparateurs).
- [x] Sont ignorés sans téléchargement : les blobs à la racine du repo et les
      extensions de documentation (`.md`, `.txt`, images). Tout le reste est
      téléchargé une fois et classé `points` ou `other`.
- [x] `state.json` sauvegardé après **chaque** fichier : un quota épuisé au
      milieu du premier passage se reprend sans rien retélécharger.

**Tests :** JSON nu, zip, fichier sans extension, non-JSON, pointeur LFS ;
diff nouveau / modifié / supprimé / inchangé ; sha incorrect refusé ; chemin
avec espaces et parenthèses correctement encodé ; reprise après `RateLimited` ;
aller-retour du cache compact ; aucune requête ne porte autre chose que les
en-têtes prévus.

### Tâche 7 : analyse d'un (fichier, pays) (§8.2, §8.3, §9)

**Fichiers :** `cartometa/carmeta/{analysis,verdicts}.py`,
`tests/test_carmeta_analysis.py`.

```python
def analyse_file_country(compact, point_idx, rules, iso) -> FileCountry
    # .frame, .rows (one per canonical tag), .families (those with a tag >= 30 points)
def geometric_verdict(row, is_parent, thresholds) -> tuple[str, str]
```

- [x] **Fusion** : les tags bruts sont ramenés à leur forme canonique *avant* le
      comptage ; un point qui porte deux écritures du même tag compte une fois.
      `raw_tags` garde les écritures d'origine, triées.
- [x] **Parent** (§8.3) : famille ni `copyright` ni `car_year` ; enfants =
      tags `car_year` strictement plus petits, d'au moins 5 points, dont ≥ 98 %
      des points portent le parent ; couverture ≥ 95 % calculée **sur ces seuls
      enfants** (c'est l'écart voulu avec le prototype).
- [x] Par tag : zones, capture, gain, verdict géométrique dans l'ordre exact du
      §9.4. Empreinte, point représentatif et carte `cells` seulement pour les
      tags qui atteignent les lignes de gain (D7).
- [x] Vérifier sur un fichier réel le format de `extra.tags[tag].color` et le
      normaliser en `#rrggbb` (D18).

**Tests :** `Antenna` couvert par des `(A)` → parent ; `Antenna` indépendant →
candidat ; `©2026` qui coïncide avec `Smallcam 2026` → jamais parent ; `Blue 24
(NA)` + `Blue 2024 (NA)` fusionnés, points dédoublonnés ; chaque ligne du
tableau §9.4 atteinte par un nuage dédié ; un tag écarté tôt n'a ni `pieces` ni
`rep`.

### Tâche 8 : choix des sources et analyse d'un pays (§7)

**Fichiers :** `cartometa/carmeta/analysis.py`, `tests/test_carmeta_sources.py`.

```python
def candidates_for(country, state) -> list[Candidate]   # primary files first, newest first
def choose_sources(candidates, families_of, rules) -> dict[str, Candidate]  # family -> file
def analyse_country(country, state, rules, load) -> dict   # the analysis/<CC>.json payload
```

- [x] Rôle d'un fichier pour un pays, d'après `state.files[*].countries` :
      *principal* si le pays pèse ≥ 50 % des points du fichier, sinon
      *multi-pays* s'il y a ≥ 1 000 points. Les deux seuils en constantes.
- [x] Candidats : principaux par date de commit décroissante (à égalité, le
      plus de points) ; à défaut **le** multi-pays le plus fourni. Par famille,
      premier candidat qui la contient à ≥ 30 points. `exclude` puis `pin` (D8).
- [x] Pays sans candidat → analyse vide (D13). Chemins de type `points` qui ne
      servent aucun pays → `unused_paths`.
- [x] Charger un même fichier une seule fois par pays ; ne lancer zones et gain
      que pour les familles attribuées à ce fichier.

**Tests :** principal préféré au multi-pays ; le plus récent gagne ; repli par
famille (le dernier fichier n'a plus `copyright` → il vient du précédent) ;
épinglage par pays et par famille ; exclusion ; pays servi seulement en
multi-pays ; fichier dont 1 600 points tombent chez le voisin sans le servir.

### Tâche 9 : verdict effectif et cas en attente (§10)

**Fichiers :** `cartometa/carmeta/verdicts.py`, `tests/test_carmeta_verdicts.py`.

```python
def effective_verdict(row, country, rules) -> tuple[str, str]
def pending_cases(analyses, rules) -> list[PendingCase]   # kind: "descriptor" | "tag"
def retained_rows(analysis, rules) -> list[dict]
```

- [x] Ordre : verdict géométrique `écarté` hors lignes de gain → inchangé ;
      clé de lexique `rejected` → `écarté` ; absente ou `pending` → `arbitrage`
      (« descripteur inconnu ») ; décision non périmée → `retenu` ou `écarté` ;
      décision périmée → `arbitrage` (« décision à revoir ») ; sans décision,
      le verdict géométrique (D5).
- [x] `pending_cases` : un cas `descriptor` par clé de lexique en attente (avec
      la liste des tags et pays concernés), un cas `tag` par verdict
      `arbitrage` sans décision valable.

**Tests :** *keep* sur un gain de 17 % → retenu ; *drop* → écarté ; *drop* à
12 %, gain passé à 40 % → redemandé, pas importé ; *keep* à 17 %, gain passé à
5 % → redemandé ; gain passé de 17 à 22 % → décision tenue ;
descripteur `pending` → en attente quel que soit le gain ; `rejected` → jamais
en attente ; la clé `<CC>|<canonique>` survit à un changement de chemin source.

### Tâche 10 : `sync` minimal et `status`

**Fichiers :** `cartometa/carmeta/{sync,cli}.py`, `tests/test_carmeta_sync.py`.

- [x] `run_sync(paths, fetch, *, force=False) -> SyncResult` : arbre → sortie
      immédiate si rien n'a changé (D14) → verrou → téléchargements et cache
      compact → pays `dirty` (tous avec `--force`) → `analysis/<CC>.json` →
      `pending.json` → `state.json` (`tree_sha`, `dirty` vidé).
- [x] Verrou : `sync.lock` créé en `O_EXCL` avec pid et date, retiré en
      `finally`. Un verrou de plus de 6 heures est repris. Verrou tenu → message
      et code 0.
- [x] `cli.py` : sous-commandes `sync [--force]` et `status` (texte : date du
      dernier passage, par pays le nombre de tags retenus / en attente /
      écartés, chemins inutilisés). Option cachée `--data-dir` pour les tests.
      Erreur réseau ou quota → message sur stderr, code 1, état cohérent.

**Tests :** sans changement : **un** appel réseau et arborescence identique
octet pour octet (critère 4) ; un fichier modifié ne refait que ses pays ;
fichier supprimé → pays réanalysés ; passage interrompu après téléchargement →
le suivant refait l'analyse sans réseau au-delà de l'arbre ; `--force` sans
réseau au-delà de l'arbre ; deux `sync` simultanés ; instantané : rien d'écrit
hors `data/cache/carmeta/`.

### Tâche 11 : contrôle sur les données réelles (critères 2 et 3)

**Fichiers :** `tests/test_carmeta_expected.py` (marqueur `carmeta_cache`).

- [x] Lancer le premier `uv run cartometa-carmeta sync` réel (≈ 1,3 Go, 46
      appels d'API ; avec un `GITHUB_TOKEN` si le quota gêne). Chronométrer
      ensuite `sync --force` : l'analyse complète doit tenir en moins de 15
      minutes.
- [x] Le test compare `analysis/` à `expected-verdicts.json` sur la clé (pays,
      forme canonique du tag attendu), pour les seuls fichiers dont la date de
      commit est encore celle de `file_dates.json`. Verdict et motif identiques,
      gain à ±0,02.
- [x] Chaque écart est inscrit dans un dictionnaire `KNOWN_GAPS` du test avec
      son explication (fusion de tags, couverture des parents, familles `car` et
      `unknown` absentes du prototype). Un écart non expliqué fait échouer le
      test. Cible : 621 retenus, 23 en arbitrage, à quelques cas près.
- [x] Comparer les sources retenues à l'annexe A.

---

## Phase C — Import et revue

### Tâche 12 : socle — origine, source carmeta, `proposal`

**Fichiers :** `cartometa/models.py`, `cartometa/review/store.py`,
`tests/test_store.py`.

- [x] `ORIGIN_CARMETA = "carmeta"`.
- [x] `CountryPaths.carmeta_metas` → `data/carmeta/<CC>.json` ; `load_metas`
      la lit entre les imports taggés et les metas manuelles. Mettre à jour la
      docstring de `CountryPaths` (les textes carmeta sont versionnés, et
      pourquoi).
- [x] `GeoRecord.proposal: dict | None = None`, de forme `{"pieces": [...]}`.
      `to_feature` n'écrit la clé que si elle existe ; `from_feature` la lit ;
      `_feature_arrondie` arrondit aussi ses pièces.

**Tests :** aller-retour d'un record avec `proposal` ; un geojson existant sans
`proposal` est réécrit **octet pour octet** (test sur un fichier de
`data/geo/` via le marqueur `real_data`) ; `load_metas` voit les cinq
sources dans l'ordre (Plonk It, RMRG, taggés, carmeta, manuelles).

### Tâche 13 : textes de la meta (§12)

**Fichiers :** `cartometa/carmeta/texts.py`, `tests/test_carmeta_texts.py`.

```python
def meta_id(country, canonical_text) -> str        # "car-" + sha1("<CC>|<canonical>")[:6]
def title(canonical, lexicon) -> str
def description(canonical, lexicon, points) -> str
def maps_url(rep, pitch) -> str
```

- [x] Titres : la table du §12, ligne pour ligne. Antenne : `(A)` → `, antenna`,
      `(NA)` → `, no antenna`, `(A+NA)` ou absente → rien.
- [x] Descriptions : un gabarit par famille dans le code, libellés pris au
      lexique, nombre de points avec séparateur de milliers anglais.
- [x] Lien : `https://www.google.com/maps/@?api=1&map_action=pano&pano=…&viewpoint=<lat>,<lng>&heading=…&pitch=…`.

**Tests :** chaque ligne de la table du §12 ; l'exemple JSON du §12 reproduit ;
identifiant stable entre deux écritures du même tag ; lien bien encodé.

### Tâche 14 : `import` (§13)

**Fichiers :** `cartometa/carmeta/importer.py`, `cli.py`,
`tests/test_carmeta_importer.py`.

```python
def plan_import(data_dir, countries, rules) -> ImportPlan   # reads only
def apply_import(data_dir, plan) -> None
# Action.kind: written | rewritten | unchanged | retexted | skipped_rejected
#            | skipped_validated | reproposed | vanished_kept | vanished_deleted
```

- [x] `plan_import` est **sans effet de bord** : il sert à `import --dry-run`,
      à `status` et au rapport. `apply_import` n'écrit que les pays dont une
      action change quelque chose.
- [x] Gardes : session de revue active (`port_is_taken` de
      `cartometa/review/server.py`) ; cache d'analyse absent ; empreinte des
      règles périmée (D6) ; collision d'identifiants → échec avec les deux tags.
- [x] Table d'états du §13, complétée par D11 et D13. `extracted_at` repris de
      l'enregistrement existant. `baseline` (D10) écrite **uniquement** quand
      une proposition ou une re-proposition est écrite.
- [x] Comparaison des pièces dans l'espace arrondi à 5 décimales : sortir
      `_same_pieces` de `cartometa/tagged/importer.py` vers `review/store.py`
      et l'importer des deux côtés.
- [x] Récapitulatif : une ligne par action, tags laissés en attente
      d'arbitrage, car metas déjà publiées du pays (catégorie `car` après
      `data/categories.json`, toutes origines) pour repérer les doublons.
- [x] `cartometa-carmeta import [CC …] [--dry-run]` ; sans code pays, tous les
      pays qui ont une analyse.

**Tests (§17) :** première écriture `proposé` ; deuxième import identique
octet pour octet et tout en `unchanged` ; `proposé` réécrit quand l'empreinte
change ; `rejeté` jamais touché ; `validé` à 85 % → rien ; à 70 % →
`proposal` posée, géométrie validée intacte, `baseline` mise à jour ;
re-proposition refusée puis même analyse → rien ; libellé corrigé au lexique →
`retexted` sur une meta validée ; tag disparu `validé` conservé, `proposé`
supprimé (texte et empreinte) ; pays sans analyse ignoré avec avertissement ;
`--dry-run` n'écrit rien ; refus si la revue tourne ; nouvelle version d'un
fichier → aucun doublon (critère 5).

### Tâche 15 : revue, côté serveur (§14)

**Fichiers :** `cartometa/review/{store,server}.py`,
`tests/test_store.py`, `tests/test_review_server.py`.

- [x] `build_queue` : une meta `validé` qui porte une `proposal` entre dans la
      file par défaut. Son item a `pieces` = pièces de la `proposal`,
      `current_pieces` = pièces validées, `reproposal: true`. Tout item gagne
      `streetview` (`maps_url`) et, pour une meta carmeta, `carmeta` (points,
      zones, capture, gain, chemin source, date — sans `baseline`).
- [x] `dismiss_proposal(paths, meta_id)` et
      `restore_reproposal(paths, meta_id, pieces, proposal)` (géométrie
      re-résolue depuis les pièces).
- [x] `apply_decision` : `validé` inchangé (`set_decision` recrée le record,
      donc efface la `proposal`) ; `rejeté` sur une re-proposition →
      `dismiss_proposal` (D12).
- [x] `apply_undo` : `restore.status == "validé"` avec `restore.proposal` →
      `restore_reproposal`.

**Tests (§17) :** la file contient la re-proposition et pas les autres metas
validées ; `A` adopte la nouvelle empreinte et efface `proposal` ; `R` garde
géométrie et statut, efface `proposal` ; `U` après `A` et après `R` rétablit
géométrie, pièces **et** `proposal` ; `done` reste juste.

### Tâche 16 : revue, côté interface (§14)

**Fichiers :** `cartometa/review/static/{app.js,index.html}`.

- [x] Superposition : pour un item `reproposal`, demander la géométrie de
      `current_pieces` à `/api/resolve` et la dessiner sous l'esquisse dans un
      style distinct (orange, tirets). Une ligne de légende dit laquelle est
      laquelle.
- [x] Bandeau `#carmeta-banner` sous le titre : points, zones, part en zones,
      gain, fichier source et date. Lien « Street View » à côté du lien source.
- [x] `undo()` envoie `restore` pour un item `reproposal`.
- [x] `editCurrent` : pour une meta `car-`, le message de refus renvoie au
      lexique de `data/carmeta/rules.json`.
- [ ] Pas de tests JS dans le dépôt : vérification manuelle sur un pays de
      test, avec une re-proposition fabriquée à la main (`A`, `R`, `U`, `Space`).

### Arrêt — revue du Mexique (critère 1)

- [ ] `uv run cartometa-carmeta import MX` puis `uv run cartometa-review MX`.
- [ ] Le mainteneur regarde les 29 empreintes et dit si comblement et lissage
      conviennent. Les réglages se corrigent dans les constantes de
      `footprint.py`, puis `sync --force` et `import MX` (les `proposé` sont
      réécrits).
- [ ] **Aucun autre pays n'est importé avant son accord.**

---

## Phase D — Arbitrage, rapport, planification

### Tâche 17 : `arbitrate` (§10)

**Fichiers :** `cartometa/carmeta/arbitrate.py`, `cli.py`,
`tests/test_carmeta_arbitrate.py`.

- [x] `run_arbitrate(paths, rules, ask, out)` avec `ask` injectable. Les
      descripteurs d'abord (un descripteur accepté peut faire apparaître des cas
      de discriminance), puis les tags. Par cas : pays, tag, points, zones, part
      en zones, gain, lien Street View.
- [x] Réponses : `k` garder, `d` écarter, `s` passer, `q` quitter. Un
      descripteur gardé demande son libellé anglais. `rules.json` sauvegardé
      après **chaque** réponse.
- [x] Refus si l'empreinte des règles de l'analyse est périmée (D6).

**Tests :** *keep* et *drop* enregistrés avec gain et date ; libellé demandé
pour un descripteur ; `q` conserve les réponses déjà données ; un cas décidé
n'est pas reproposé ; un second passage sans cas en attente ne modifie pas le
fichier.

### Tâche 17 bis : `prune` (D21)

**Fichiers :** `cartometa/carmeta/prune.py`, `cli.py`,
`tests/test_carmeta_prune.py`.

- [x] `vanished_validated(data_dir, countries, rules)` : les metas `car-`
      validées absentes des tags retenus, avec le motif (tag absent de
      l'analyse, ou écarté et pourquoi). Vient de `plan_import`.
- [x] `cartometa-carmeta prune [CC …] [--yes]` : affiche chaque meta (titre,
      motif), demande `o/N`, supprime texte et empreinte. Mêmes gardes que
      `import` (revue active, analyse absente ou périmée). Un pays sans analyse
      n'est jamais purgé.

**Tests :** une meta validée dont le tag a disparu est listée puis supprimée ;
refus → rien n'est écrit ; une meta `rejeté` n'est jamais listée ; après
suppression, le tag qui réapparaît est proposé de nouveau ; pays sans analyse
ignoré.

### Tâche 18 : rapport et `status` complet (§16)

**Fichiers :** `cartometa/carmeta/report.py`, `report_template.html`,
`sync.py`, `tests/test_carmeta_report.py`.

- [x] Gabarit dérivé de `page_template.html` du prototype (canvas par tag
      décodé depuis `cells`, lien Street View), copié dans le paquet. Polices
      système : le rapport doit s'ouvrir hors ligne.
- [x] Sections : changements du repo ; par pays, tags retenus à importer, cas
      en attente, metas validées dont l'empreinte a bougé, tags disparus
      (tout cela vient de `plan_import`, en lecture seule) ; chemins et
      descripteurs inconnus.
- [x] `status` reprend le même résumé en texte.

**Tests :** le rapport est autonome (aucune URL externe hors liens Street View
et GitHub) ; chaque section apparaît quand elle a du contenu ; les titres venus
des tags sont échappés ; `status` et rapport donnent les mêmes compteurs.

### Tâche 19 : journal, notification, tâche planifiée (§16)

**Fichiers :** `cartometa/carmeta/sync.py`, `scripts/carmeta-sync.plist`,
`scripts/install-carmeta-sync.sh`, `scripts/install-carmeta-sync.ps1`,
`docs/carmeta-sync.md`.

- [x] Une ligne par passage utile dans `logs/carmeta-sync.log` (date, fichiers
      changés, à importer, en attente, ou l'erreur). Rien quand rien n'a changé.
- [x] Notification au mieux : `osascript` sous macOS, PowerShell sous Windows,
      jamais bloquante, jamais fatale.
- [x] macOS : agent `launchd` quotidien ; le script d'installation renseigne le
      chemin absolu de `uv` et du dépôt (launchd n'a pas le `PATH` du shell).
      Windows : `Register-ScheduledTask` équivalent.
- [x] `docs/carmeta-sync.md` (en anglais, comme les autres) : le cycle
      `sync → arbitrate → import → review → build`, l'installation sur les deux
      systèmes, `rules.json` champ par champ, que faire quand un libellé est
      faux.

**Tests :** ligne de journal écrite sur changement, absente sinon ; une
notification qui échoue ne change pas le code de retour.

---

## Phase E — Publication

### Tâche 20 : build (§15)

**Fichiers :** `cartometa/build/dataset.py`, `tests/test_build_dataset.py`.

- [x] Chaque meta publiée gagne `streetview` (son `maps_url`) et `color`
      (`carmeta.color`), absents quand la meta n'en a pas.
- [x] Un orphelin `car-` est fatal, avec `man-` (D17) ; le message nomme
      `data/carmeta/<CC>.json`.

**Tests :** meta carmeta validée publiée avec lien et couleur ; meta `proposé`
absente ; meta validée avec `proposal` publiée avec sa géométrie **validée**,
sans trace de `proposal` dans la sortie ; les metas des autres origines sont
publiées à l'identique.

### Tâche 21 : viewer et licence (§15, §12)

**Fichiers :** `viewer/{app.js,style.css,licence.html}`.

- [x] `creerCarte` : sans `thumb`, une pastille à la couleur du tag (neutre à
      défaut) portant le titre, à la place de la vignette.
- [x] `ouvrirLoupe` : lien « Street View example » quand `meta.streetview`
      existe.
- [x] « Add to Anki » : déjà masqué sans image (`viewer/anki.js`,
      `reinitialiser`) — à vérifier, rien à coder.
- [x] `licence.html` : une ligne d'attribution à carmeta (CC BY-NC 4.0).
- [ ] Vérification manuelle : `uv run cartometa-build MX --skip-images` puis
      `npx wrangler pages dev dist`, thèmes clair et sombre, largeur mobile.

### Tâche 22 : bout en bout et documentation

- [ ] Rejouer le cycle complet sur deux pays (un mono-fichier, un servi par un
      fichier multi-pays) et cocher les six critères de succès du §17.
- [ ] Simuler une nouvelle version d'un fichier (changer un sha dans
      `state.json`) : aucun doublon, aucune décision redemandée.
- [x] `README.md` : section `cartometa-carmeta` et renvoi à
      `docs/carmeta-sync.md` ; corriger la phrase sur les sources de textes
      (`data/carmeta/` est versionné).
- [x] Suite complète verte.

---

## 4. Couverture de la spec

| § | Tâches | § | Tâches |
|---|---|---|---|
| 5 Données | 1, 12 | 12 Meta produite | 13, 14 |
| 6 Récupération | 6 | 13 Import | 14 |
| 7 Pays et source | 5, 8 | 14 Revue | 15, 16 |
| 8 Tags | 2, 7 | 15 Build et viewer | 20, 21 |
| 9 Zones et gain | 3, 7 | 16 Planification, rapport | 10, 18, 19 |
| 10 Arbitrage | 1, 9, 17 | 17 Tests et critères | chaque tâche ; 11, 22 |
| 11 Empreinte | 4 | 18 Choix à corriger | aucun n'est bloquant |

| Critère de succès | Vérifié par |
|---|---|
| 1. Empreintes du Mexique | arrêt après la tâche 16 |
| 2. Verdicts conformes au prototype | tâche 11 (`KNOWN_GAPS`) |
| 3. Analyse en moins de 15 minutes | tâche 11 |
| 4. `sync` sans changement : un appel, aucune écriture | tâche 10 |
| 5. Ni doublon ni décision redemandée | tâches 9, 14, 22 |
| 6. Publication avec lien et pastille, sans `proposé` | tâches 20, 21 |

## 5. Risques

- **Premier passage** : 1,3 Go et 46 appels d'API sur un quota de 60 par
  heure. La reprise par fichier (tâche 6) rend un échec sans conséquence.
- **Polygonisation en shapely pur** : suffisante dans le prototype pour les
  cartes, pas mesurée pour les empreintes. Si un tag de 100 000 points dépasse
  quelques secondes, la fusion par lignes de la tâche 4 est le premier levier.
- **Repo carmeta en Git LFS** : non vérifié ; la tâche 6 détecte le pointeur au
  lieu de planter, et le remède (domaine `media.githubusercontent.com`) tient
  en une ligne.
- **Forme des empreintes** : seul point de la spec non validé visuellement.
  C'est la raison de l'arrêt Mexique, placé avant l'arbitrage et le rapport
  pour que les réglages bougent tôt.

## 6. État au 2026-11-18

Tâches 1 à 22 codées, testées et commitées sur la branche `carmeta-sync`
(810 tests verts). Le Mexique est importé (29 propositions, non commitées) et
attend la revue du mainteneur : c'est l'arrêt prévu. Restent ouverts, cases
non cochées ci-dessus :

- la revue du Mexique et le réglage éventuel des constantes de `footprint.py` ;
- l'ouverture dans un navigateur des trois interfaces touchées (revue, viewer,
  rapport) : leur JavaScript est vérifié en syntaxe et en identifiants, pas à
  l'écran ;
- l'arbitrage des 36 cas en attente, puis l'import des 42 autres pays ;
- l'installation de la tâche planifiée (`scripts/install-carmeta-sync.sh`).

Écarts par rapport au plan, tous dans le sens de la spec :

- **Téléchargements** : transferts compressés et reprise par `Range` d'un
  fichier coupé (le premier passage réel perdait les derniers kilo-octets des
  gros fichiers, de façon répétée).
- **Empreinte** : fermeture et comblement faits en vectoriel (tampon positif
  puis négatif, anneaux intérieurs sous 25 cases supprimés) plutôt que sur un
  raster : même résultat, sans grille de plusieurs millions de cases.
- **Référence d'empreinte** : simplifiée à une demi-case et arrondie à 100 m,
  et le fichier `data/carmeta/<CC>.json` écrit une meta par ligne. Le fichier
  du Mexique passe de 1,6 Mo à 230 Ko.
- **Pastille du viewer** : appliquée à toute meta sans image, pas seulement
  aux metas carmeta, pour garder la grille alignée.
- **Contrôle sur données réelles** : 957 verdicts sur 965 strictement
  identiques au prototype, 8 de même verdict avec des chiffres différents
  (expliqués dans `tests/test_carmeta_expected.py`), 4 lignes nouvelles de la
  famille `car`. Analyse complète en 35 secondes.

### Suite du 2026-11-18, après la revue du Mexique

- Mexique : les 29 empreintes validées par le mainteneur, réglages de
  `footprint.py` inchangés.
- Arbitrage : les 36 cas acceptés (23 décisions `keep`, 13 descripteurs avec
  leur libellé anglais dans `rules.json`).
- Import des 42 autres pays : 615 propositions, 644 metas carmeta au total.
- **Tuiles** (demande du mainteneur) : le build dessine l'image des metas
  carmeta — fond de la couleur de la voiture, blanc à défaut, texte blanc ou
  noir si la voiture est blanche ou grise. Remplace la pastille CSS comme
  illustration principale ; celle-ci reste le repli des builds sans images.
