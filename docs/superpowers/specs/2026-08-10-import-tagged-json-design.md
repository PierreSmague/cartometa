# cartometa-import-tagged — import de JSON de points taggés

Design validé le 2026-08-10.

## 1. Objectif

Transformer un JSON de points taggés à la main (format carte GeoGuessr :
`{"name": …, "customCoordinates": [{lat, lng, extra: {tags: […]}}, …]}`) en
metas Cartometa **proposées**, chacune avec son empreinte pré-dessinée, que le
mainteneur valide ou rejette d'une touche dans `cartometa-review`.

Deux fichiers réels motivent le design :

| Fichier | Points | Tags | Morphologie |
|---|---|---|---|
| `input/Architecture.json` | 1 725 | 14 | zones diffuses (Pologne, espacement médian ~10-20 km) |
| `input/ua antennas.json` | 5 402 | 19 | traces de routes (Ukraine, espacement médian ~1,7 km) |

Décisions actées avec le mainteneur :

- **une meta par tag**, aucun filtrage à l'import (les tags de mois « June »,
  « May »… passent aussi — le tri se fait à la revue) ;
- **mode route** : corridor fidèle de **500 m de large au maximum** (buffer
  250 m autour du tracé reconstruit) ;
- **mode zone** : enveloppe concave par cluster, **gonflée de 10 km** ;
- le mode est **choisi à l'import** (`--mode route|zone`), pas deviné ;
- **pays auto-détecté** point par point (Natural Earth admin-0) ; un tag qui
  déborde sur deux pays donne une meta par pays ; récapitulatif par pays en
  fin d'import ;
- **titre = nom du tag, description = titre recopié**, catégorie passée à
  l'import (`--category`) ;
- la validation oui/non se fait dans **`cartometa-review` existant**, via un
  nouveau statut **« proposé »** : pièces préchargées dans la file par défaut,
  jamais publié tant que non validé.

### Critères de succès

- `uv run cartometa-import-tagged "input/ua antennas.json" --mode route
  --category car` produit ~19 metas proposées (× pays touchés), corridors
  ≤ 500 m de large, et affiche le récapitulatif tag × pays.
- `uv run cartometa-review UA` montre ces metas dans la file par défaut, le
  contour proposé déjà dessiné et cadré ; `A` publie, `R` rejette, la retouche
  pièce par pièce fonctionne.
- `uv run cartometa-build UA` n'exporte **aucune** meta restée « proposée ».
- Un re-run de l'import ne crée aucun doublon et ne touche pas aux metas déjà
  décidées (validées, rejetées, ou dont le contour a été retouché).
- Un fichier mondial passe par le même chemin sans traitement spécial :
  l'éclatement par pays le découpe tout seul.

### Hors périmètre

- L'affichage des points source individuels dans la revue (le contour proposé
  suffit à juger ; V2 si le besoin se confirme).
- Tout enrichissement du texte (dates de couverture, comptes de points…) : la
  description est le titre, point.
- Les images : ces metas n'en ont pas à l'import.
- Le croisement de tags (antenne × mois).

## 2. Vue d'ensemble

```
input/xxx.json
      │  cartometa-import-tagged xxx.json --mode … --category …
      ▼
┌ parse ─ groupe par tag ─ pays par point ─ géométrie par (tag, pays) ┐
      │                                                               │
      ▼                                                               ▼
data/metas/<CC>-tagged.json                 data/geo/<CC>.geojson
(titre, description, catégorie)            (pièces, statut « proposé »)
      │                                                               │
      └────────────── uv run cartometa-review <CC> ───────────────────┘
                            A → validé   R → rejeté
```

Nouveau module `cartometa/tagged/` avec un point d'entrée
`cartometa-import-tagged` dans `pyproject.toml`, sur le modèle des deux
extracteurs existants.

## 3. Où vont les textes : `data/metas/<CC>-tagged.json`

Le précédent est RMRG (`data/metas/<CC>-rmrg.json`) : une source externe,
regénérable en relançant l'importeur sur le fichier d'entrée conservé. Les
metas taggées suivent le même schéma — **gitignorées**, régénérables — plutôt
que `data/manual/`, qui reste réservé à ce qu'un humain a tapé et qui est
irremplaçable.

Conséquence assumée : comme pour Plonk It et RMRG, un clone frais a les
empreintes (versionnées dans `data/geo/`) mais pas les textes. Le mainteneur
publie depuis sa copie complète ; les fichiers d'entrée sont à conserver dans
`input/` comme les captures Plonk It. Si un jour ces JSON collaboratifs
doivent être partagés, c'est le fichier d'entrée qu'on versionnera, pas sa
transformation.

`load_metas()` (review) et le chargement du build gagnent le troisième
suffixe : imported, rmrg, **tagged**, puis manual — dans cet ordre.

## 4. Le format d'entrée, et ce qu'on en garde

- `customCoordinates[*].lat/lng` : la position — tout ce qui compte.
- `extra.tags` : liste de tags ; un point à N tags compte dans N metas.
- Un point sans tags est ignoré (compté dans le récapitulatif).
- Tout le reste (heading, pitch, zoom, panoId, panoDate) est ignoré.
- `name` (nom du fichier logique) sert au récapitulatif et au calcul des ids.

Anomalie observée dans les données réelles : un point porte son `panoId` dans
`extra` au lieu de la racine — sans incidence, le champ est ignoré.

## 5. Rattachement au pays

Chaque point est rattaché par point-dans-polygone sur les silhouettes Natural
Earth admin-0 (déjà en cache `data/cache/`, déjà téléchargées par la revue),
accélérées par un `STRtree` shapely construit une fois par import.

- Point dans aucun pays (mer, lacune du trait de côte Natural Earth) : rattaché
  au pays le plus proche si à moins de **10 km**, sinon écarté et compté.
- Une meta est créée par couple (tag, pays) ayant au moins un point.
- Le récapitulatif final liste chaque tag avec sa répartition :
  `Roof Type - "Podhale"   PL 44 pts → 3 pièces   SK 2 pts → 1 pièce`
  — c'est le garde-fou contre les débordements accidentels de frontière ; une
  meta née de 2 points orphelins se rejette en une touche à la revue.

## 6. Géométrie

Tous les calculs métriques se font dans une projection locale par (tag, pays) :
longitude multipliée par `cos(latitude moyenne)`, kilomètres via 111 km/°.
À l'échelle d'un pays et pour des buffers de 250 m à 10 km, la distorsion est
négligeable, et cela évite toute nouvelle dépendance (pas de pyproj).

### Mode route (`--mode route`)

1. **Arbre couvrant minimal** (Prim, O(n²) en Python pur — ~7 M distances pour
   le pire tag réel, quelques secondes, acceptable) sur les points du couple
   (tag, pays).
2. Les arêtes de plus de **5 km** sont coupées : l'arbre devient une forêt,
   chaque composante est un tronçon de route distinct. (Espacement médian
   observé 1,7 km, p90 ~8 km : 5 km relie les relevés consécutifs sans
   ponter deux routes parallèles.)
3. Buffer de **250 m** autour des arêtes restantes et des points isolés
   (un point seul devient une pastille de 250 m de rayon), puis union.
4. Pré-simplification à ~50 m : borne le poids des fichiers sans dégrader un
   ruban de 500 m.

### Mode zone (`--mode zone`)

1. Même arbre couvrant, coupé à **40 km** : les composantes sont les clusters.
2. Cluster de ≥ 3 points : `shapely.concave_hull(ratio=0.4)`, puis buffer
   **+10 km**. Cluster de 1-2 points : buffer direct de 10 km (pastille ou
   capsule).
3. Pré-simplification à ~500 m.

Les deux seuils de coupe (5 km / 40 km) sont des options CLI avec ces défauts
(`--link-km`), pour ajuster sans toucher au code si un fichier réel les prend
en défaut.

### Les trous, et l'extension du format de pièce

Un corridor bufferisé peut être troué : une rocade fermée produit un anneau
dont l'intérieur ne doit **pas** être couvert (à 250 m de buffer, le trou est
la ville entière). Or la pièce `polygon` actuelle est un anneau sans trous.

Le descripteur s'étend donc : `{"kind": "polygon", "ring": […],
"holes": [[…], …]}` — `holes` optionnel, absent pour tout dessin à la main.

- `pieces.py` : `_contour` passe les trous à `Polygon(ring, holes)`.
- `sketch.js` : le rendu Leaflet accepte nativement `[extérieur, trou…]` ;
  l'édition à la souris ne produit jamais de trous, elle n'en crée donc pas —
  `Backspace` supprime la pièce entière, trous compris, comme aujourd'hui.

Chaque polygone de l'union devient une pièce : l'empreinte reste l'union de
ses pièces, retouchable morceau par morceau dans la revue.

## 7. Les metas produites

| Champ | Valeur |
|---|---|
| `id` | `tag-` + 6 hexa de SHA-1 sur `nom_fichier\|tag\|pays` — déterministe, donc re-run idempotent ; préfixe distinct de `man-` (4 hexa) et des ids Plonk It |
| `country` | le pays détecté |
| `tier` | `manual` (étiquette d'affichage, aucune logique dessus) |
| `title` | le tag, tel quel |
| `description` | le titre, recopié |
| `category` | la valeur de `--category`, validée contre les sept slugs |
| `source_url` | vide (un nom de fichier n'est pas une URL) |
| `description_origin` | `imported` — marque que le texte reste à écrire |
| `origin` | `tagged` (le build n'utilise `origin` pour aucune logique — vérifié) |
| `source_file` / `source_tag` | provenance, pour relecture humaine du fichier |
| `image`, `maps_url`, `maps_latlon` | `null` |

## 8. Le statut « proposé »

Troisième statut dans `models.py` : `STATUS_PROPOSED = "proposé"` (graphie
française, comme `validé`/`rejeté` — ce sont des données stockées).
`STATUSES` reste le couple des **décisions** : `set_decision` continue de
n'accepter que validé/rejeté, on ne « décide » pas proposé.

| Point de contact | Comportement |
|---|---|
| `build_queue` (revue) | une meta dont le GeoRecord est « proposé » reste dans la file **par défaut**, avec ses pièces — seul changement : n'exclure que les statuts dans `STATUSES` |
| `A` / `R` dans la revue | inchangés : écrasent le statut par validé/rejeté |
| `U` (annuler) | restaure l'enregistrement précédent — donc le statut proposé et ses pièces ; à couvrir par un test |
| build du site | inchangé : `EXPORTABLE = (validé,)` exclut déjà tout le reste |
| compteur `legacy_statuses` du build | ne compte plus « proposé » comme statut inconnu (sinon chaque import déclencherait l'alerte de données douteuses) |
| `save_geo` / arrondi 5 décimales | inchangés, les pièces importées passent par le même chemin d'écriture |

L'import écrit les GeoRecords « proposé » via `save_geo`, en **refusant
d'écraser** tout enregistrement existant dont le statut est validé ou rejeté,
ou dont les pièces ont divergé de ce que l'import précédent avait posé (id
déterministe → comparaison directe). Re-runs sûrs : seul ce qui est encore
« proposé » et intact est régénéré.

## 9. Cadrage de la carte dans la revue

Aujourd'hui `frame()` cadre le point Maps, sinon la silhouette du pays. Un
corridor de 500 m perdu dans l'Ukraine serait invisible au zoom pays.

Ajout en tête de priorité : si l'item a des pièces à coordonnées (`rect`,
`polygon`), cadrer leur boîte englobante (padding existant). Les pièces sans
coordonnées (`country`, `admin1`, `clip`) retombent sur le comportement
actuel. Bénéficie aussi au mode `--all` existant.

## 10. CLI

```
uv run cartometa-import-tagged <fichier.json> --mode route|zone --category <slug>
    [--buffer-m 250] [--link-km 5.0|40.0 selon le mode] [--hull-buffer-km 10]
    [--dry-run]
```

- `--mode` et `--category` obligatoires (catégorie validée contre les sept).
- `--dry-run` : tout le calcul et le récapitulatif, aucune écriture.
- Erreurs franches : JSON invalide, `customCoordinates` absent, catégorie
  inconnue, aucun point taggé.
- Le récapitulatif tag × pays s'affiche dans tous les cas (points, pièces,
  points écartés, metas sautées car déjà décidées).

## 11. Poids et performances

- `data/geo/UA.geojson` grossira de quelques Mo (corridors de milliers de
  sommets, pré-simplifiés à 50 m, arrondis à 5 décimales). Versionné : accepté.
- Le build protège déjà les rubans fins : `effective_tolerance` borne la
  tolérance de simplification par la largeur moyenne de la géométrie — un
  test de non-régression le verrouille avec un corridor réel.
- Import : quelques secondes par tag dominées par le MST en Python pur ;
  aucun besoin de numpy/scipy.

## 12. Tests

Points synthétiques, pas de dépendance aux fichiers réels :

- **route** : une chaîne → un ruban ; deux tronçons séparés de > 5 km → deux
  pièces ; un point isolé → une pastille ; une boucle fermée → une pièce avec
  trou, et le trou survit à `resolve_pieces` ;
- **zone** : deux clusters à > 40 km → deux enveloppes ; cluster de 2 points →
  capsule de 10 km ; l'enveloppe contient tous ses points gonflés ;
- **pays** : un nuage à cheval sur une frontière → deux metas, récapitulatif
  correct ; point en mer < 10 km → rattaché ; > 10 km → écarté ;
- **statuts** : la file par défaut contient les proposées avec pièces ; le
  build ne les exporte pas ; `legacy_statuses` reste à zéro ; `A`/`R`
  écrasent ; `U` restaure « proposé » et ses pièces ;
- **idempotence** : deux runs successifs → fichiers identiques ; run après
  décision ou retouche → la meta décidée est intacte ;
- **régression build** : un corridor de 500 m survit à la simplification par
  défaut (largeur finale > 250 m).

## 13. Risques identifiés

| Risque | Traitement |
|---|---|
| Le MST ponte deux routes parallèles proches (< 5 km) | acceptable en V1 : le corridor reste honnête à 250 m près ; `--link-km` ajustable |
| `concave_hull` trop lâche ou trop serrée selon la densité | `ratio` exposé en option si les fichiers réels le demandent ; défaut 0.4 |
| Fichier d'entrée perdu → textes irrécupérables sur clone frais | même contrat que Plonk It/RMRG : conserver `input/` ; les empreintes, elles, sont versionnées |
| Collision d'ids `tag-` (6 hexa, ~50 metas) | probabilité ~10⁻⁵ ; l'import échoue franchement si deux couples (tag, pays) produisent le même id |
| La revue tourne pendant l'import (data/geo réécrit des deux côtés) | même règle que pour git : ne pas importer pendant une session de revue active ; l'import échoue proprement si le port 8799 répond |
