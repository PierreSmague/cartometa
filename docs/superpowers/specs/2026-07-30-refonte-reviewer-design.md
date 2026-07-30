# Refonte du reviewer — polygones tracés à la main

Design validé le 2026-07-30.

## Pourquoi

Le pipeline actuel devine le polygone d'une méta en vectorisant la zone rouge
de l'encart cartographique Plonk It, après avoir calibré une transformation
pixel → WGS84 sur la silhouette du pays. Ça marche, mais ça n'a de sens que
tant que Plonk It est la source unique.

Ce n'est plus le cas : les métas viendront désormais de nombreuses sources, et
leur emprise géographique sera définie à la main dans tous les cas. La
détection automatique devient un poids mort — du code à maintenir, des seuils à
régler, des calibrations à surveiller, pour un résultat qui sera de toute façon
redessiné.

On supprime donc toute la détection, on garde l'extraction Plonk It telle
quelle, et on refond le reviewer pour qu'il devienne l'unique endroit où une
géométrie est définie.

## Décisions structurantes

Quatre choix pris pendant le brainstorming, dont tout le reste découle.

**Table rase.** Les 685 métas déjà revues (318 `validé`, 367 `corrigé`) ne sont
pas conservées. Leur géométrie vient d'une vectorisation dont on ne veut plus.
`data/geo/` est remis à zéro, `data/calib/` supprimé. Les 843 métas sont
retracées à la main. L'historique git garde tout, si on veut comparer.

**Aucun pré-remplissage.** Une méta arrive vierge, sans exception — y compris
les 241 métas de section 1 dont l'emprise est pourtant « tout le pays ». Un
geste de plus, mais aucune règle implicite à retenir et aucune géométrie
posée sans décision humaine.

**Les métas manuelles vivent à part et sont versionnées.** `data/metas/` est
gitignoré parce que régénérable par `cartometa-extract` ; une méta saisie à la
main ne l'est pas et ne peut donc pas vivre là.

**Les morceaux se cumulent.** L'emprise d'une méta est l'union d'une liste de
morceaux hétérogènes — deux rectangles disjoints, trois régions admin-1, un
contour libre plus la silhouette du pays. Nécessaire de toute façon pour
sélectionner plusieurs régions, et ça évite d'englober trop large une méta qui
couvre deux zones séparées.

## Périmètre

### Supprimé

| Élément | Motif |
|---|---|
| `cartometa/geo/calibrate.py` | calibration pixel → WGS84 |
| `cartometa/geo/silhouette.py` | détection de l'encart cartographique |
| `cartometa/geo/vectorize.py` | vectorisation de la zone rouge |
| `cartometa/geo/confidence.py` | score de confiance d'une géométrie devinée |
| `cartometa/geo/cli.py` + entry point `cartometa-geo` | plus de pipeline à lancer |
| `tests/test_calibrate.py`, `test_silhouette.py`, `test_vectorize.py`, `test_confidence.py`, `test_geo_cli.py`, `test_review_offset.py` | tests des modules supprimés |
| sections `[cream] [red] [silhouette] [calibration] [vectorize] [spot]` de `config/defaults.toml` | seuils de détection d'image |
| `data/calib/` | calibrations par pays |
| README §3 « Générer les polygones », §4 réécrit, `docs/rapport-pologne.md` | documentent le pipeline supprimé |

Le décalage au clavier (flèches) et la correction de rayon disparaissent avec
le reste : ils servaient à rattraper une géométrie devinée. Il n'y en a plus.

### Inchangé

`cartometa/extract/` dans son intégralité — parsing HTML, catégories,
résolution des liens Maps, cache. La commande `cartometa-extract` garde sa
signature et son comportement.

`cartometa/geo/reference.py` (silhouette Natural Earth admin-0, résolution
slug → code ISO) et `cartometa/geo/export.py` restent dans `geo/`.

### Ajouté

| Module | Responsabilité |
|---|---|
| `cartometa/geo/admin1.py` | dataset Natural Earth admin-1 : téléchargement, extraction par pays, résolution d'un `adm1_code` en géométrie |
| `cartometa/review/store.py` | lecture/écriture des trois fichiers d'un pays, fusion en une file de revue |
| `cartometa/review/pieces.py` | résolution d'une liste de morceaux en une géométrie unique |

## Fichiers de données

```
data/metas/<CC>.json               métas importées Plonk It      gitignoré (inchangé)
data/manual/<CC>/metas.json        métas saisies à la main       VERSIONNÉ
data/manual/<CC>/images/<id>.png   images des métas manuelles    VERSIONNÉ
data/geo/<CC>.geojson              géométries + statut + morceaux  versionné
data/cache/ne_10m_admin_1_states_provinces.geojson   41 Mo       gitignoré
data/cache/admin1/<CC>.geojson     régions du pays extraites     gitignoré
```

Le dataset admin-1 complet pèse 41 Mo et n'est lu qu'une fois : au premier
usage du mode subdivisions sur un pays, on en extrait les régions de ce pays
dans `data/cache/admin1/<CC>.geojson`. Les lancements suivants ne touchent plus
au gros fichier.

`.gitignore` n'a rien à gagner : `data/cache/` y est déjà, ce qui couvre les
deux fichiers admin-1. Le point de vigilance est inverse — aucune règle ne doit
couvrir `data/manual/`, dont le contenu est irremplaçable.

## Modèle de données

### `GeoRecord`

```python
@dataclass
class GeoRecord:
    id: str
    geometry: dict[str, Any] | None
    pieces: list[dict[str, Any]]
    status: str            # "validé" | "rejeté"
```

`confidence` et `warnings` disparaissent : sans détection automatique, il n'y a
plus rien à scorer ni à signaler.

Une méta absente de `data/geo/<CC>.geojson` est « à faire ». Il n'y a pas de
statut `auto` ni `corrigé` : une géométrie présente est par construction
tracée à la main.

### Les morceaux

Le client n'envoie jamais un polygone Natural Earth. Il envoie la liste de ce
qui a été posé :

```json
[
  {"kind": "country"},
  {"kind": "admin1", "code": "FRA-2345"},
  {"kind": "rect",    "bounds": [2.1, 48.7, 2.6, 49.0]},
  {"kind": "polygon", "ring": [[2.30, 48.85], [2.41, 48.88], [2.38, 48.79]]}
]
```

`bounds` est `[min_lon, min_lat, max_lon, max_lat]`. `ring` est une liste d'au
moins trois sommets `[lon, lat]`, non fermée — la fermeture est ajoutée par le
serveur.

Le serveur résout `country` et `admin1` depuis Natural Earth, construit `rect`
et `polygon` depuis les coordonnées reçues, calcule l'union shapely, valide, et
écrit la géométrie résultante **et** la liste des morceaux.

Trois raisons de faire ainsi plutôt que de laisser le client envoyer la
géométrie finale :

1. La silhouette d'un pays ou d'une région reste garantie authentique — c'est
   déjà le principe en place pour la touche `P` aujourd'hui.
2. On n'envoie pas des mégaoctets de coordonnées par requête.
3. Une méta déjà tracée peut être rouverte avec ses morceaux, et un morceau
   retiré sans tout redessiner.

### `MetaRecord`

Gagne `origin: str = "plonkit"`, valant `"manual"` pour une méta saisie à la
main.

`tier` (`country` / `regional` / `spot`) reste stocké et affiché à titre
informatif — c'est ce que la page Plonk It déclarait — mais **plus aucune
logique n'en dépend**. Le viewer ne s'en sert déjà pas. Une méta manuelle
reçoit `tier = "manual"`.

Les identifiants des métas manuelles sont préfixés : `man-<4 hex>`. Aucune
collision possible avec les identifiants Plonk It, qui sont 4 caractères sans
préfixe.

## Interface du reviewer

### Clavier

| Touche | Action |
|---|---|
| `D` | mode **rectangle** — deux clics posent un morceau |
| `C` | mode **contour libre** — clics successifs, fermeture en repassant sur le premier sommet ou par `Entrée` |
| `S` | mode **subdivisions** — chaque clic ajoute/retire la région admin-1 sous le curseur |
| `P` | ajoute la silhouette du **pays entier** (instantané, aucun clic) |
| `Retour arrière` | retire le dernier morceau, ou le dernier sommet si un contour est en cours |
| `Échap` | sort du mode de dessin courant sans rien effacer |
| `0` | vide entièrement la zone en cours |
| `A` | enregistre l'union des morceaux → `validé` |
| `R` | marque `rejeté` |
| `Espace` | méta suivante |
| `Maj+Espace` | méta précédente |
| `U` | annule la dernière décision |
| `N` | ouvre le formulaire de méta manuelle |

Les modes sont **collants** : après un rectangle posé on reste en mode
rectangle, poser le second ne demande aucune touche. C'est ce qui rend le
cumul de morceaux naturel plutôt que laborieux.

Détails de comportement :

- Le contour libre demande au moins 3 sommets. Il se ferme par un clic à moins
  de 12 pixels du premier sommet, ou par `Entrée`. Un contour de moins de 3
  sommets est ignoré à la fermeture.
- `Retour arrière` est contextuel : en mode contour avec des sommets en cours,
  il retire le dernier sommet ; sinon il retire le dernier morceau posé.
- `Échap` au milieu d'un rectangle (un seul coin posé) ou d'un contour
  abandonne le morceau en cours ; les morceaux déjà posés restent.
- `A` sur une zone vide ne fait rien et le dit dans la barre d'état — on
  n'enregistre jamais une méta sans emprise.
- `R` ignore les morceaux en cours : un rejet reste un rejet.
- `Maj+Espace` navigue seulement : il ne défait aucune décision. Seul `U` le
  fait.

### Affichage

Morceaux posés en vert plein semi-transparent, morceau en cours de tracé en
vert pointillé élastique suivant le curseur, point Maps en bleu — c'est la
vérité terrain, inchangée depuis la version actuelle.

Barre d'état : `3 morceaux — A enregistrer · ⌫ retirer · 0 vider`, et le nom du
mode actif quand il y en a un.

En mode subdivisions, le client charge une fois `data/cache/admin1/<CC>.geojson`
via `GET /api/admin1`. La région sous le curseur se surligne au survol et la
sélection est instantanée, sans aller-retour serveur. Le client ne renvoie que
les `adm1_code`.

Comme toute méta arrive vierge, la carte se cadre par défaut sur le point Maps
s'il existe, sinon sur l'étendue du pays.

### File de revue

Par défaut, la file contient les métas sans statut, dans l'ordre du fichier
(qui suit l'ordre de la page Plonk It), les métas manuelles ensuite.

`cartometa-review <CC> --all` rouvre tout, y compris `validé` et `rejeté`. Une
méta rouverte revient avec ses morceaux, retirables un par un — c'est ce qui
permettra de repasser sur un pays quand une nouvelle source donnera mieux.

Le compteur affiche la position dans la file et le total du pays.

### Formulaire de méta manuelle

`N` ouvre un panneau :

- **Titre** — obligatoire
- **Description** — obligatoire
- **Catégorie** — liste (`bollards`, `poteaux`, `vehicule`, `vegetation`,
  `signalisation`, `autre`), pré-remplie par `infer_category` sur le texte
  saisi, modifiable
- **Source** — URL libre, optionnelle
- **Image** — dépôt de fichier ou `Ctrl+V`

Coller une capture d'écran directement est le geste le plus court et sera le
cas courant ; le dépôt de fichier couvre le reste.

À la validation, la méta est écrite dans `data/manual/<CC>/metas.json`,
affichée immédiatement, et le tracé peut commencer.

Le serveur vérifie via PIL que les octets reçus forment bien une image,
plafonne à 8 Mo, et écrit sous un nom **qu'il génère lui-même**
(`man-1a2b.png`) — jamais un nom fourni par le client, même sur une écoute
restreinte à 127.0.0.1.

## API du serveur de revue

| Route | Rôle |
|---|---|
| `GET /api/queue` | file de revue : métas fusionnées des deux sources, avec leurs morceaux |
| `GET /api/country-polygon` | silhouette Natural Earth du pays (aperçu) |
| `GET /api/admin1` | régions admin-1 du pays, avec `adm1_code` et nom |
| `POST /api/decision` | `{id, status, pieces}` — résout, unit, valide, écrit |
| `POST /api/undo` | `{id}` — retire le statut et la géométrie de la méta |
| `POST /api/meta` | crée une méta manuelle (texte) et renvoie son identifiant |
| `POST /api/meta/image` | dépose l'image d'une méta manuelle déjà créée |

L'ordre est imposé : `POST /api/meta` d'abord, qui attribue l'identifiant
`man-*`, puis `POST /api/meta/image` avec cet identifiant. C'est le serveur qui
nomme le fichier image à partir de l'identifiant qu'il a lui-même attribué, ce
qui rend impossible l'écriture hors de `data/manual/<CC>/images/`.

Les gardes-fous existants sont conservés : validation shapely de toute
géométrie avant écriture, bornes WGS84, surface non nulle, écriture atomique
via `write_json_atomic`, messages d'erreur explicites plutôt qu'échec
silencieux.

## Export

`EXPORTABLE = ("validé",)`. `--include-auto` disparaît avec le statut `auto`.

`export_viewer` lit les deux sources de métas — `data/metas/<CC>.json` et
`data/manual/<CC>/metas.json` — et les fusionne avant de joindre les
géométries. La découverte des pays depuis `data/geo/*.geojson` ne change pas.

Un pays n'ayant que des métas manuelles doit pouvoir s'exporter : l'absence de
`data/metas/<CC>.json` n'est plus une erreur fatale si le fichier manuel
existe.

## Tests

Supprimés : les six fichiers listés en périmètre.

Ajoutés :

- `test_pieces.py` — résolution de chaque type de morceau, union de morceaux
  hétérogènes, MultiPolygon pour des morceaux disjoints, rejet d'un `ring` de
  moins de 3 sommets, de coordonnées hors bornes WGS84, d'un `adm1_code`
  inconnu, d'un `kind` inconnu, d'une liste vide.
- `test_admin1.py` — extraction des régions d'un pays depuis un dataset
  factice, résolution `adm1_code` → géométrie, code absent.
- `test_store.py` — fusion des deux sources, file par défaut vs `--all`,
  préservation des statuts entre deux lectures, méta manuelle sans homologue
  importé.
- `test_manual_meta.py` — création avec identifiant `man-*`, écriture de
  l'image sous nom généré, refus d'octets qui ne sont pas une image, refus
  d'un dépassement de taille, absence d'effet d'un nom de fichier fourni par
  le client.

Adaptés : `test_export.py` (statut unique, double source), `test_cli.py` si
nécessaire.

Aucun test ne touche le réseau — le dataset admin-1 est injecté via un
`downloader` comme le fait déjà `reference.ensure_dataset`.

## Migration

Opération unique, pendant l'implémentation, pas une commande permanente :

1. Chaque `data/geo/<CC>.geojson` est réécrit en
   `{"type": "FeatureCollection", "features": []}`.
2. `data/calib/` est supprimé du dépôt.
3. Le premier `cartometa-export` suivant videra `viewer/data/` — la carte
   restera blanche jusqu'à ce que des métas soient retracées. C'est attendu.

Tout reste récupérable dans l'historique git.

## Ce qui n'est pas dans le périmètre

- Édition du texte ou de l'image d'une méta **importée**. Seules les métas
  manuelles sont éditables ; une méta Plonk It dont le texte déplaît se rejette.
- Régions administratives de niveau 2. Le niveau 1 couvre le besoin exprimé.
- Import automatique depuis d'autres sources que Plonk It. Les autres sources
  passent par le formulaire manuel.
- Simplification ou lissage des géométries produites. Les contours Natural
  Earth 10m sont utilisés tels quels, comme aujourd'hui pour la touche `P`.
