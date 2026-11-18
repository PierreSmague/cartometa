# cartometa-carmeta — intégration automatisée des car metas

Design validé avec le mainteneur le 2026-11-18. Destiné à l'implémenteur : il
doit pouvoir planifier le travail à partir de ce document sans revenir vers le
mainteneur, sauf sur les points listés en §18.

Matériel de référence : `docs/specs/2026-11-18-carmeta-spike/` (prototype
jetable qui a produit les chiffres ci-dessous) et la page d'exemples validée
<https://claude.ai/artifact/EwkwwT1KUMpSesrXisW4Kh>.

## 1. Objectif

Le repo <https://github.com/iggedi-ig-ig/carmeta> publie, par pays, des JSON de
points Street View taggés par une IA (voiture, année, copyright, antenne…). Ces
tags sont fiables. Le but est d'en tirer des metas Cartometa de catégorie `car`
sans travail manuel autre que la validation finale.

Le pipeline :

1. surveille le repo et détecte une modification ;
2. filtre les tags : ne garde que les familles utiles, le niveau le plus fin,
   et les tags qui **éliminent une partie du pays** ;
3. soumet les cas limites du filtre à un arbitrage, une fois pour toutes ;
4. écrit les tags retenus comme metas **proposées**, empreinte pré-tracée, que
   le mainteneur valide ou rejette dans `cartometa-review`.

Ordre de grandeur au 2026-11-15 : 45 fichiers, 43 pays, 4,3 M de points,
965 tags candidats → **621 retenus**, 23 en arbitrage, 321 écartés.

## 2. Décisions actées avec le mainteneur

| Sujet | Décision |
|---|---|
| Validation | La revue manuelle reste la voie normale. Le filtre réduit ce qui y arrive ; l'arbitrage porte sur le filtre, pas sur la revue. Depuis le 2026-11-18, `cartometa-carmeta accept` valide en lot les propositions telles que calculées, quand le mainteneur fait confiance au lot (premier import : Mexique revu à la main, le reste accepté). |
| Familles gardées | voiture × année, copyright, `Antenna`, `BL`/`Brakelight`, flous, `Exposed`, `Snow`, `Smallcam` seul. |
| Familles écartées | année, mois, année-mois, météo, codes pays, subdivisions, climats Köppen, `Part n`/`Pn`, séparateurs, `Gen 4`/`Normal Gen 4`, tous les `No …` sauf `No Car <année>`. |
| Granularité | Seul le niveau le plus fin : un tag couvert par des tags voiture × année plus fins est écarté. |
| Zone | Au moins 30 points du tag qui se suivent. Un point isolé n'est pas une zone. |
| Discriminance | Pas un seuil de surface. Le tag doit sélectionner des zones distinctes ou éliminer une zone ; disséminé partout = sans intérêt. Mesuré par le **gain régional** (§9). |
| Seuils | Gain ≥ 20 % : retenu. 10–20 % : arbitrage. < 10 % : écarté. Moins de 35 % des points en zones : écarté. |
| Arbitrage | Liste à trancher avant import ; décision mémorisée dans un fichier de règles versionné. |
| Illustration | Pas de capture. Une **tuile** générée au build : fond uni de la couleur de la voiture (blanc à défaut), titre en blanc — en noir si la voiture est blanche ou grise (décision du 2026-11-18, après la revue du Mexique). Plus un lien Street View vers un point représentatif. |
| Texte | Titre normalisé en anglais, description générée d'une phrase. |
| Tracé | Union des zones, trous entre routes comblés, découpée aux frontières. |
| Fichier source | Par pays et par famille : le fichier le plus récent qui contient la famille. |
| Mise à jour | Une meta validée n'est re-proposée que si la nouvelle empreinte recouvre l'ancienne à moins de 80 %. Un rejet est définitif. |
| Exécution | Tâche planifiée locale, macOS et Windows. Elle n'écrit que le rapport et la liste d'arbitrage, hors git. L'import est lancé à la main. |
| Publication | Inchangée : `cartometa-build` puis `wrangler`, à la main, après la revue. Sur le site, les metas carmeta sont derrière une option « Enable advanced car metas », décochée par défaut (décision du 2026-11-18) : elles ne doivent ni ouvrir les résultats ni les noyer. |

## 3. Hors périmètre

- Captures automatiques, API Street View Static (la tuile du §15 n'est pas une capture).
- Publication ou deploy automatiques ; GitHub Actions.
- Croisement de familles (copyright × voiture, voiture × mois).
- Détection automatique de doublons avec les car metas manuelles existantes
  (148 aujourd'hui) : le rapport les liste, le mainteneur rejette en revue.
- Édition des textes carmeta dans l'interface de revue (touche `M`) : ils se
  corrigent dans le lexique du fichier de règles.
- `cartometa-import-tagged` : inchangé, il reste l'outil des JSON taggés à la
  main. Son algorithme (arbre couvrant quadratique, enveloppe gonflée de
  10 km) ne convient pas ici : un tag peut avoir 100 000 points, et il trace un
  disque autour de chaque point isolé.

## 4. Vue d'ensemble

```
repo carmeta (GitHub)
      │  cartometa-carmeta sync            (planifié, quotidien)
      ▼
data/cache/carmeta/          ← miroir, analyse, rapport, cas en attente (gitignoré)
      │  cartometa-carmeta arbitrate       (à la main, si des cas attendent)
      ▼
data/carmeta/rules.json      ← décisions, lexique, seuils (versionné)
      │  cartometa-carmeta import [CC …]   (à la main)
      ▼
data/carmeta/<CC>.json       ← textes des metas (versionné)
data/geo/<CC>.geojson        ← empreintes « proposé »
      │  cartometa-review <CC>             A → validé   R → rejeté
      ▼
cartometa-build → wrangler   (inchangé)
```

Nouveau module `cartometa/carmeta/`, un seul point d'entrée
`cartometa-carmeta` à sous-commandes (`sync`, `arbitrate`, `import`,
`prune`, `status`), déclaré dans `pyproject.toml` comme les autres.

## 5. Où vivent les données

| Chemin | Versionné | Contenu |
|---|---|---|
| `data/cache/carmeta/files/` | non | Copie des fichiers du repo, par sha de blob. |
| `data/cache/carmeta/state.json` | non | Par chemin : sha du blob, date du commit, date de récupération. |
| `data/cache/carmeta/analysis/<CC>.json` | non | Résultat du filtre par pays : une ligne par tag, avec ses mesures et son empreinte. |
| `data/cache/carmeta/report.html` | non | Rapport du dernier `sync`. |
| `data/carmeta/rules.json` | **oui** | Seuils, lexique, épinglages de sources, décisions d'arbitrage. |
| `data/carmeta/<CC>.json` | **oui** | Textes des metas proposées ou décidées. |
| `data/geo/<CC>.geojson` | oui | Empreintes et statuts (existant). |

`data/metas/` est gitignoré : les textes carmeta ne peuvent pas y aller, ils
seraient perdus entre deux machines alors que les empreintes validées, elles,
sont versionnées. `CountryPaths` gagne une propriété `carmeta_metas` et
`load_metas` lit cette quatrième source.

Les textes sont régénérables mais versionnés quand même : ils portent la
référence d'empreinte du §13, qui ne se reconstruit pas.

## 6. Récupération du repo

- Détection : un appel à `GET /repos/iggedi-ig-ig/carmeta/git/trees/main?recursive=1`
  donne le sha de chaque fichier. Comparé à `state.json`, il dit quels chemins
  sont nouveaux, modifiés ou supprimés. Aucun changement : `sync` sort sans
  rien écrire.
- Téléchargement : `raw.githubusercontent.com`, bibliothèque standard. Un
  fichier `.zip` contient un JSON. Un fichier **sans extension** peut être un
  JSON (`CentralAmerica/CostaRica/CostaRica-CR-17.05.26`) : on reconnaît le
  format au contenu, pas au nom.
- Date d'un fichier : celle de son dernier commit
  (`GET …/commits?path=<chemin>&per_page=1`). **Jamais la date du nom** : les
  noms mélangent formats européen et américain (`Ireland 08_01_26` date du
  1er août 2026).
- Sans authentification, l'API autorise 60 appels par heure : assez pour un
  usage quotidien, et pour le premier passage (une arborescence + 45 dates).
  `GITHUB_TOKEN`, s'il est défini, est utilisé.
- En-tête `User-Agent` générique. Aucune donnée personnelle dans les requêtes.
- Le premier passage télécharge environ 1,3 Go. L'implémenteur peut ne garder
  qu'une forme compacte (lat, lng, tags, panoId, heading) plutôt que les JSON
  bruts.

Format d'un fichier : `{"name", "customCoordinates": [{lat, lng, heading,
pitch, panoId, extra: {tags: […], panoDate}}], "extra": {"tags": {<tag>:
{order, color}}}}`. Un point peut porter de 0 à une dizaine de tags. Quelques
points factices portent uniquement des séparateurs (latitude vers −85°) : on
écarte tout point sans panoId ou hors de tout pays.

## 7. Pays et fichier source

**Pays d'un point** : Natural Earth admin-0, comme `CountryIndex`, mais en
vectorisé (`shapely.contains_xy` sur des géométries préparées, puis plus proche
pays à moins de 0,09° pour les points côtiers). `CountryIndex.country_of` point
par point est trop lent pour 850 000 points. `numpy` devient une dépendance
déclarée (elle est déjà là via shapely).

**Un fichier sert un pays** s'il en est le fichier *principal* (le pays pèse au
moins 50 % de ses points) ou, à défaut, un fichier *multi-pays* (au moins
1 000 points dans le pays). Les autres points sont ignorés : le fichier
Luxembourg contient 1 626 points en Allemagne, le fichier Irlande toute
l'Irlande du Nord.

**Choix pour un pays** :

1. candidats = ses fichiers principaux, du plus récent au plus ancien (à date
   égale, le plus de points) ;
2. s'il n'en a aucun, le fichier multi-pays qui a le plus de points chez lui ;
3. **pour chaque famille**, on prend le premier candidat qui contient au moins
   un tag de cette famille à 30 points ou plus.

Le point 3 évite de perdre une famille quand une nouvelle version l'abandonne :
en Australie, au Canada et au Pérou, le dernier fichier n'a plus les copyrights
ou `BL`, qui viennent donc du fichier précédent. `rules.json` permet d'épingler
ou d'exclure un chemin. Résultat actuel en annexe A.

Un chemin inconnu qui ne sert aucun pays apparaît dans le rapport.

## 8. Du tag brut au tag candidat

### 8.1 Famille

Évaluée dans cet ordre, sur le tag débarrassé de ses espaces de bord :

| Famille | Règle | Sort |
|---|---|---|
| `sep` | contient une suite de 3 `─`, `—` ou `═` | écarté |
| `copyright` | `©` + 4 chiffres | **gardé** |
| `year` | `19xx` ou `20xx` seul | écarté |
| `month` | entier de 1 à 12 seul | écarté |
| `yearmonth` | `nn-nn` | écarté |
| `weather` | `Clear`, `Some Clouds`, `Overcast` | écarté |
| `koppen` | code de climat (`Csa`, `BSk`, `Dfb`, `ET`…) | écarté |
| `parts` | `Pn`, `Part n` | écarté |
| `bl` | `BL`, `Brakelight` (*backlight* / *brakelight*, même indice) | **gardé** |
| `neg` | `No BL`, `No Antenna`, `No Front Blur`, `No Snow` | écarté |
| `country` | 2 majuscules formant un code ISO | écarté |
| `admin` | subdivision (16 Länder allemands aujourd'hui) | écarté |
| `camera_gen` | `Gen 4`, `Normal Gen 4` | écarté |
| `smallcam` | `Smallcam` seul | **gardé** |
| `antenna` | `Antenna` seul | **gardé** |
| `blur` | `Front Blur`, `New Blur` | **gardé** |
| `exposed` | `Exposed`, `Exposed Back` | **gardé** |
| `snow` | `Snow` | **gardé** |
| `car_year` | `<descripteur> <année>` avec suffixe optionnel `(A)`, `(NA)`, `(A+NA)` | **gardé** |
| `car` | descripteur de voiture sans année (`Black`, `White`…) | **gardé** |
| `unknown` | le reste | arbitrage |

`BL` doit être testé avant `country`. `No Car 2023` est un `car_year` comme les
autres (la voiture est invisible, c'est une vraie car meta). Les séparateurs
(`───Month───`, `───Country───`) et le champ `order` regroupent les tags dans
certains fichiers : c'est un indice utile pour ranger un mot inconnu, pas une
source fiable (l'Afrique du Sud n'en a aucun).

### 8.2 Forme canonique

Les fichiers n'écrivent pas tous pareil : `Blue 24 (NA)`, `Blue 2024 (NA)`,
`Blue Car 2024`, `Blue Car Antenna 2024`, `Gray`/`Grey`. Un `car_year` est
ramené à un triplet :

- **descripteur** : sans le mot `Car`, sans le mot `Antenna`, `Grey` → `Gray` ;
- **année** sur 4 chiffres ;
- **antenne** : `A`, `NA`, `A+NA` ou absente. `Antenna` dans le descripteur
  vaut `A`.

La forme canonique s'écrit `Blue 2024 (NA)`. Deux tags bruts d'un même fichier
et d'un même pays qui donnent la même forme sont **fusionnés** (leurs points
s'additionnent).

Le **lexique** de `rules.json` liste les descripteurs connus, avec le libellé
anglais qui sert au titre. Un descripteur absent du lexique envoie le tag en
arbitrage (« descripteur inconnu »). Lexique initial en annexe B.

### 8.3 Niveau le plus fin

Un tag `P` est un parent, donc écarté, si :

- sa famille n'est ni `copyright` ni `car_year` ;
- il existe des tags `car_year` enfants : plus petits que lui, et dont 98 % des
  points au moins portent aussi `P` ;
- ces enfants couvrent ensemble au moins 95 % des points de `P`.

Exemples réels : `Antenna` en Autriche, France, Pays-Bas, Pologne (couvert par
les tags `(A)`), `Exposed` aux États-Unis, `Black` au Bangladesh. À l'inverse,
`Antenna` en Turquie ou en Suède est une dimension indépendante et reste
candidat.

Un copyright n'est jamais parent : `©2026` peut coïncider avec `Smallcam 2026`,
ce sont deux indices différents.

Le prototype calcule la couverture sur tous les enfants puis filtre ; le
produit doit la calculer directement sur les enfants `car_year`.

## 9. Zones et gain

Tout se calcule **par (fichier source, pays)**, sur les seuls points du pays.
`docs/specs/2026-11-18-carmeta-spike/zones.py` fait foi sur les détails.

### 9.1 Repère

- Projection locale en kilomètres : `x = lng · 111,320 · cos(lat moyenne)`,
  `y = lat · 110,574`. Si les longitudes s'étalent sur plus de 300°, on ajoute
  360 aux négatives (antiméridien).
- `D` = racine de l'aire de l'enveloppe convexe des points : la « taille » de
  la couverture du pays.
- `δ` = distance médiane au plus proche voisin, tous tags confondus (un
  échantillon de 300 points suffit) : l'espacement des points du fichier, de
  0,5 km aux Pays-Bas à 2 km en Afrique du Sud.

### 9.2 Zones d'un tag

1. Grille de hachage de côté `L = max(3δ, 1 km)` sur les points du tag.
2. Composantes connexes des cases occupées, en 8-voisinage.
3. Une composante d'au moins **30 points** est une **zone**. Les autres points
   sont ignorés.

`capture` = part des points du tag qui tombent dans une zone.

Cette définition a remplacé un seuil de part locale, qui effaçait les vieilles
couvertures diluées par les plus récentes. Elle tient à ce qu'une vraie
couverture forme des tronçons continus, alors qu'une erreur de classification
est un point seul.

### 9.3 Gain régional

Grille d'analyse de côté `s = D/60`, borné entre 1,5 et 25 km.

- `tot[c]` = nombre de points du pays dans la case `c`, `cnt[c]` = nombre de
  points **en zone** du tag.
- Rayon régional `R = 0,10 · D`. `totR` et `cntR` = sommes de `tot` et `cnt`
  sur le disque de rayon `R` autour de chaque case.
- Cases *connues* : celles où `tot > 0` et `totR ≥ 30`.
- Part régionale `p = cntR / totR` sur les cases connues ; `q = p / Σp`.
- `KL = Σ q · log2(q · N)`, `N` = nombre de cases connues.
- **gain = 1 − 2^(−KL)**.

Lecture : la part du pays qu'on élimine en voyant le tag. Un tag confiné à la
moitié du pays donne 50 % ; présent partout, ou disséminé partout à l'échelle
`R`, il donne 0 %, quelle que soit sa surface. La mesure couvre les deux cas
demandés : sélectionner des zones (`Black Striped 2024` au Mexique, 75 %) et
éliminer une zone (`©2026` au Costa Rica, 35 %).

`R` vaut 5 km au Luxembourg, 120 km en Afrique du Sud, 300 km en Australie.

### 9.4 Verdict

Dans l'ordre, le premier qui s'applique :

| Condition | Verdict |
|---|---|
| moins de 30 points dans le pays | écarté : moins de 30 points |
| parent (§8.3) | écarté : couvert par des tags plus fins |
| aucune zone | écarté : aucune zone de 30 points |
| `capture` < 35 % | écarté : points surtout isolés |
| gain < 10 % | écarté : non discriminant |
| gain < 20 % | **arbitrage** : discriminance limite |
| sinon | **retenu** |

Une décision d'arbitrage (§10) l'emporte sur les deux dernières lignes.
Les quatre seuils sont dans `rules.json`.

## 10. Arbitrage et fichier de règles

`data/carmeta/rules.json`, versionné, lisible et modifiable à la main :

```json
{
  "thresholds": {"min_zone_points": 30, "min_capture": 0.35,
                 "gain_drop": 0.10, "gain_keep": 0.20, "reproposal_iou": 0.80},
  "sources": {"pin": {}, "exclude": []},
  "lexicon": {"Blue": {"label": "Blue car", "status": "accepted"},
              "Ford": {"label": "Ford", "status": "pending"}},
  "decisions": {"LU|Blue 2024": {"decision": "keep", "gain": 0.17,
                                 "decided_at": "2026-11-20"}}
}
```

- Un cas en attente est un tag en verdict *arbitrage* sans décision, ou un
  descripteur `pending`.
- `cartometa-carmeta arbitrate` parcourt les cas en attente, affiche pour
  chacun pays, tag, points, zones, part en zones, gain et le lien Street View,
  et enregistre `keep` ou `drop`. Le rapport HTML montre la carte de chaque cas.
- Une décision est **durable**. Elle n'est redemandée que si le gain a bougé de
  plus de 10 points depuis la décision.
- La clé d'une décision est `<CC>|<forme canonique>` : elle survit au
  changement de nom des fichiers.

23 cas attendent aujourd'hui (annexe C).

## 11. Empreinte

À partir des zones d'un tag :

1. rastériser chaque zone sur la grille de côté `L` ;
2. fermeture morphologique de rayon 2 cases, pour combler les vides entre
   routes voisines ; boucher les trous intérieurs de moins de 25 cases ;
3. polygoniser, lisser (dilatation de `L/2`, simplification à `L/4`) ;
4. sortir une pièce `polygon` par polygone, plus une pièce `{"kind": "clip"}` :
   la découpe aux frontières est alors faite par `resolve_pieces`, sur la même
   silhouette que la touche `F` de la revue.

`geometry_to_pieces` de `cartometa/tagged/geometry.py` est réutilisable tel
quel (plafond `MAX_RING_POINTS`, trous).

Le mainteneur a validé les zones sur la grille d'analyse, pas la forme finale
du polygone. Les valeurs de l'étape 2 et 3 sont donc un point de départ : voir
le premier critère de succès du §17.

## 12. La meta produite

**Identité** : `car-` + 6 hexadécimaux de `sha1("<CC>|<forme canonique>")`.
Stable d'une version de fichier à l'autre et d'une écriture du tag à l'autre.
Une collision fait échouer l'import avec un message, comme pour `tag-`.

**Enregistrement** dans `data/carmeta/<CC>.json` :

```json
{"id": "car-3fa2b1", "country": "MX", "tier": "manual", "origin": "carmeta",
 "category": "car", "title": "Blue car, unexposed · 2024",
 "description": "Street View coverage from 2024 shot with the unexposed blue car. Footprint computed from 13,750 locations tagged by carmeta.",
 "description_origin": "generated",
 "source_url": "https://github.com/iggedi-ig-ig/carmeta",
 "extracted_at": "…", "image": null,
 "maps_url": "https://www.google.com/maps/@?api=1&map_action=pano&pano=…",
 "maps_latlon": [19.4, -99.1],
 "carmeta": {"canonical": "Blue Unexposed 2024", "family": "car_year",
             "raw_tags": ["Blue Unexposed 2024"],
             "source_path": "NorthAmerica/Mexico/Mexico 12_23_25.json",
             "source_sha": "…", "source_date": "2026-05-06",
             "points": 13750, "zones": 45, "capture": 0.90, "gain": 0.42,
             "baseline": {"type": "MultiPolygon", "coordinates": []}}}
```

`ORIGIN_CARMETA = "carmeta"` s'ajoute dans `models.py`. `extracted_at` est
conservé d'un passage à l'autre : deux imports identiques doivent donner des
fichiers identiques octet pour octet.

**Titre** (anglais), d'après le lexique :

| Tag canonique | Titre |
|---|---|
| `Blue 2024 (NA)` | `Blue car, no antenna · 2024` |
| `Blue 2023 (A)` | `Blue car, antenna · 2023` |
| `Black 2025 (A+NA)`, `Black 2025` | `Black car · 2025` |
| `No Car 2023` | `No car visible · 2023` |
| `Smallcam 2025` | `Smallcam · 2025` |
| `©2025` | `©2025 copyright` |
| `BL`, `Brakelight` | `Brake light` |
| `Antenna`, `Snow`, `Smallcam` | libellé du lexique |

**Description** : une phrase générée par famille, qui dit ce qu'on voit et
l'année, suivie du nombre de points. Les gabarits sont dans le code, les
libellés dans le lexique.

**Lien Street View** : un seul, vers le point de la plus grande zone le plus
proche de son centre. `maps_url` suit le format ci-dessus avec `viewpoint`,
`heading` (celui du JSON) et `pitch` (−35 par défaut, réglable).
`maps_latlon` porte les coordonnées : la revue les affiche déjà comme point
bleu.

**Licence** : carmeta est en CC BY-NC 4.0, compatible avec le CC BY-NC-SA des
données Cartometa. L'attribution passe par `source_url` et par une ligne
ajoutée à `viewer/licence.html`.

## 13. Import et mises à jour

`cartometa-carmeta import [CC …] [--dry-run]` écrit les metas des tags
*retenus* ou arbitrés `keep`. Il refuse de tourner si une session
`cartometa-review` est active (même garde que `cartometa-import-tagged`) ou si
l'analyse en cache est absente. Les tags encore en attente d'arbitrage sont
simplement laissés de côté et comptés dans le récapitulatif.

Par meta, selon l'état de son enregistrement dans `data/geo` :

| État existant | Action |
|---|---|
| aucun | écrite, statut `proposé` |
| `proposé` | réécrite avec la nouvelle empreinte |
| `rejeté` | rien, jamais re-proposée |
| `validé`, recouvrement ≥ 80 % | rien |
| `validé`, recouvrement < 80 % | **re-proposition** (ci-dessous) |

**Recouvrement** : intersection sur union entre la nouvelle empreinte calculée
et la **référence** (`carmeta.baseline`), c'est-à-dire la dernière empreinte
calculée qui a été présentée au mainteneur. L'import met cette référence à jour
chaque fois qu'il écrit une proposition ou une re-proposition, et seulement
là : la revue n'a rien à enregistrer de plus. On ne compare pas à la géométrie
validée : si le mainteneur l'a retouchée à la main, l'écart serait permanent et
la meta reviendrait à chaque passage. Une re-proposition refusée ne revient
donc pas non plus, tant que l'empreinte calculée ne bouge pas de nouveau.

**Re-proposition** : la meta validée **reste publiée telle quelle**. Sa
nouvelle empreinte est rangée à côté, dans un champ `proposal` du `GeoRecord`
(persisté dans les `properties` du geojson uniquement quand il existe). Passer
la meta en `proposé` la dépublierait jusqu'à la prochaine revue, ce qu'on ne
veut pas.

**Tag disparu** (absent du nouveau fichier, ou désormais écarté par le filtre) :

- meta `validé` : conservée, signalée dans le rapport. Elle n'est jamais
  supprimée d'office, mais `cartometa-carmeta prune [CC …]` liste ces metas
  (avec le motif : tag absent du fichier, ou désormais écarté) et les
  supprime, texte et empreinte, après confirmation une par une. Cas type :
  une couverture intégralement remplacée (`©2019` n'existe plus). Si le tag
  réapparaît plus tard, il est re-proposé comme un tag neuf ;
- meta `proposé` jamais décidée : supprimée, texte et empreinte.

Un deuxième import sans changement n'écrit rien.

## 14. Revue

Changements dans `cartometa/review/` :

- La file inclut les metas `validé` qui portent une `proposal`. L'ancienne
  empreinte et la nouvelle sont affichées superposées, dans deux couleurs.
  `A` adopte la nouvelle (retouchable avant), `R` garde l'ancienne. Dans les
  deux cas `proposal` est effacée et le statut reste `validé`.
- Un bandeau sur les metas `car-` : points, zones, part en zones, gain,
  fichier source et sa date. C'est ce bandeau qui porte l'information « 40 %
  des points seulement sont dans les zones tracées ».
- Les car metas déjà publiées du pays (catégorie `car`, toutes origines) sont
  listées dans le récapitulatif de l'import, pour repérer les doublons.

`U` (annuler) doit rétablir l'état d'avant, `proposal` comprise.

## 15. Build et viewer

- `cartometa/build/dataset.py` publie `maps_url` pour les metas qui en ont un
  (champ `streetview`), et la couleur du tag quand le JSON carmeta en donne une.
- `cartometa/build/images.py` dessine pour chaque meta carmeta une tuile
  (vignette et pleine taille, WebP) : le titre sur la couleur de la voiture,
  l'année sur sa propre ligne. C'est une vraie image : galerie, loupe, cartes
  Anki et userscript la consomment sans cas particulier.
- `viewer/app.js` : la loupe affiche un lien « Street View example ». Une meta
  sans aucune image (build fait avec `--skip-images`, meta manuelle sans
  capture) garde une pastille de même taille dessinée par la page.
- Rien d'une meta `proposé` n'est publié (déjà vrai).

## 16. Tâche planifiée et rapport

`cartometa-carmeta sync` est la commande planifiée, une fois par jour :

1. vérifie le repo ; aucun changement → sortie silencieuse, code 0 ;
2. télécharge les fichiers changés, refait l'analyse des pays concernés ;
3. écrit `analysis/`, `report.html` et la liste des cas en attente ;
4. notifie.

Elle **n'écrit jamais ailleurs que dans `data/cache/carmeta/` et `logs/`** :
pas dans `data/carmeta/`, pas dans `data/geo/`, aucune commande git. Elle peut
donc tourner pendant que le mainteneur travaille sur une autre branche. Un
verrou empêche deux exécutions simultanées. `sync --force` refait l'analyse
sans changement du repo (après une modification des règles).

**Deux systèmes** : la commande est identique ; `scripts/` reçoit une recette
par système (un agent `launchd` pour macOS, une tâche du Planificateur pour
Windows) et la doc dit comment l'installer. La notification est faite au mieux
(notification système) ; le rapport et une ligne dans `logs/carmeta-sync.log`
sont la trace fiable.

**Rapport** (`report.html`, autonome, modèle :
`2026-11-18-carmeta-spike/page_template.html`) :

- ce qui a changé dans le repo ;
- par pays : tags retenus à importer, cas en attente d'arbitrage, metas
  validées dont l'empreinte a bougé, tags disparus ;
- une carte par tag (couverture, zones, partie éliminée) et son lien Street
  View ;
- chemins et descripteurs inconnus.

`cartometa-carmeta status` redonne ce résumé en texte.

## 17. Tests et critères de succès

Tests : `uv run python -m pytest`, réseau toujours simulé, nuages de points
synthétiques.

- Familles et forme canonique : table tirée du vocabulaire réel (annexe B).
- Parent : `Antenna` couvert par des `(A)` ; `©2026` jamais parent.
- Zones : chaîne de 30 points → une zone ; 29 → aucune ; points isolés ignorés.
- Gain : tag uniforme ≈ 0 ; confiné à une moitié ≈ 50 % ; présent sur 90 %
  ≈ 10 % ; disséminé en damier fin ≈ 0.
- Source : principal contre multi-pays, repli par famille, épinglage.
- Import : idempotence, rejet définitif, seuil de re-proposition, tag disparu.
- Revue : adoption et refus d'une `proposal`, annulation.

Critères de succès :

1. **Avant tout import de masse**, le mainteneur regarde en revue les
   empreintes du Mexique (29 metas) et dit si le comblement et le lissage du
   §11 lui conviennent. Les réglages se corrigent là.
2. Sur le repo au commit du 2026-11-15, les verdicts correspondent à
   `expected-verdicts.json` : mêmes verdicts à quelques cas près, tout écart
   expliqué (fusion de tags, couverture des parents).
3. L'analyse complète des 45 fichiers prend moins de 15 minutes sur un
   portable (le prototype : environ 6).
4. Un `sync` sans changement du repo ne fait qu'un appel réseau et n'écrit
   rien.
5. Une nouvelle version d'un fichier ne crée aucun doublon et ne redemande
   aucune décision déjà prise.
6. `cartometa-build` publie une car meta validée avec son lien Street View et
   sa pastille, et aucune meta `proposé`.

## 18. Choix de Claude, à corriger si besoin

Ces points n'ont pas été discutés un par un ; le mainteneur a approuvé
l'ensemble.

- Lien Street View unique (la question proposait aussi « un par zone »).
- Pastille colorée à la place de la vignette.
- `Europe Gen4` (données de novembre 2025) utilisé pour la Belgique, la
  Suisse, Chypre et le Portugal.
- Difficulté non renseignée.
- Seuil de 50 % pour un fichier principal, 1 000 points pour un multi-pays.
- Redemander une décision si le gain bouge de plus de 10 points.
- Préfixe d'identifiant `car-`, emplacement `data/carmeta/`.
- Commande `arbitrate` en ligne de commande plutôt que dans la revue.

`BL` veut dire *backlight* ou *brakelight* (confirmé par le mainteneur) : c'est
le même indice que `Brakelight` aux États-Unis. Les deux écritures ont la même
forme canonique, `BL`, et le même titre, `Brake light`.

Laissé à l'implémenteur : format compact du cache, représentation de la
référence d'empreinte (un polygone simplifié suffit), structure interne du
module, forme exacte du bandeau et de la superposition en revue.

## Annexe A — Sources retenues au 2026-11-15

| Pays | Fichier | Commit | Familles |
|---|---|---|---|
| AT | Austria 70K 01.02.26 | 05-06 | car, antenna |
| AU | AU 1.5km 17.8.26 EXPERIMENTAL | 08-18 | car, blur |
| AU | Aus 13.04.26 *(repli)* | 05-06 | copyright, bl |
| BA | bosnia ai | 05-06 | car |
| BD | bangla 30K 20.04.26 | 05-06 | car, copyright, bl |
| BE, CH, CY, PT | Europe Gen4 (27.11.25) *(multi-pays)* | 05-06 | car |
| BG | bulgaria vit 500m | 05-06 | car, copyright |
| BR | Brazil Vit (19.03.26) | 05-06 | car, copyright |
| CA | Canada 17.08.26 - 2km | 08-18 | car |
| CA | canada vit 09.04.26 *(repli)* | 05-06 | copyright, bl |
| CL | chile 30.04.26 | 05-06 | car, copyright, bl |
| CR | CostaRica-CR-17.05.26 | 06-06 | copyright |
| CZ | Czech Republic 27.01.26 | 05-06 | car, antenna |
| DE | Germany Car Meta | 05-06 | car |
| DK | Denmark 08.02.26 | 05-06 | car |
| EE, LT, LV | Baltics 70K (24.03.26) *(multi-pays)* | 05-06 | car, copyright, antenna |
| ES | Spain June 26 | 06-06 | car |
| FI | FI 44K | 05-06 | car |
| FR | France Vali 27.01.26 | 05-06 | car, antenna |
| GB | UK 04.05.26 | 05-06 | car, copyright, antenna |
| GR | Greece 31.01.26 | 05-06 | car |
| HR | croatia vit | 05-06 | car, antenna |
| HU | Hungary 24.03.26 | 05-06 | car, copyright, antenna |
| IE | Ireland 08_01_26 | 08-01 | car |
| IT | italy 17.01.26 | 05-06 | car |
| LU | Luxembourg 30K 15.02.26 | 05-06 | car, antenna |
| MX | Mexico 12_23_25 | 05-06 | car |
| NL | NL Car Meta (20.01.26) | 05-06 | car, antenna |
| NO | NO 37K | 05-06 | car, blur |
| NZ | NZ 30K (16.07.26) | 07-16 | car, bl |
| PE | Peru 30k (17.07.26) | 07-17 | car, copyright |
| PE | pe 11k (02.05.26) *(repli)* | 05-06 | bl |
| PL | Poland 100K | 05-06 | car, antenna |
| RO | Romania 27.01.26 | 05-06 | car |
| SE | Sweden 27.01.26 AI | 05-06 | car, antenna, blur |
| SI | slovenia vit | 05-06 | car |
| SK | Slovakia 27.01.26 | 05-06 | car, antenna |
| TH | Thailand 190K | 05-06 | car |
| TR | Turkey 15.11.26 | 11-15 | car, antenna, snow |
| US | us 850k 01.01.26 | 06-24 | car, bl, exposed |
| ZA | za 30.04.26 | 05-06 | copyright, smallcam |

Fichiers non utilisés : `Spain 27.01.26 - 110K`, `Ireland + Northern Ireland
27.01.26`, `türkiye vit 05.04.26`, `nz vit` (remplacés par une version plus
récente qui a les mêmes familles).

Metas retenues par pays : AT 11, AU 42, BA 2, BD 15, BE 8, BG 12, BR 19, CA 35,
CH 7, CL 16, CR 1, CY 1, CZ 16, DE 5, DK 10, EE 9, ES 11, FI 14, FR 22, GB 21,
GR 9, HR 9, HU 18, IE 13, IT 16, LT 13, LU 6, LV 7, MX 29, NL 18, NO 13, NZ 16,
PE 18, PL 18, PT 6, RO 7, SE 34, SI 12, SK 10, TH 23, TR 8, US 38, ZA 3.

## Annexe B — Lexique initial des descripteurs

Acceptés d'office (couleurs et variantes de carrosserie déjà établies) :
`Blue`, `Black`, `White`, `Gray`, `Red`, `Navy`, `Striped`, `White-Blue`,
`Black / Gray`, `No Car`, `Smallcam`, et les variantes d'exposition `Blue
Unexposed`, `Blue Bit Exposed`, `Blue Very Exposed`, `Blue Striped`, `Black
Striped`, `Unexposed Blue`, `Exposed Blue`, `Blue Exp`, `Black Exp`, `Navy
Exp`, `Gray Exp`, `Striped Exp`.

En attente d'arbitrage au premier passage : `Truck`, `Lowcam`, `Blue Lowcam`,
`Striped Lowcam`, `Electronic`, `Electronic (Black)`, `Electronic (White)`,
`White EV`, `Black (Sticker)`, `Alberta Car`, `Ford`, `New Blur`, `Glitched
Blur`, `Gray Exposed Back`.

## Annexe C — Cas de discriminance limite au 2026-11-15

| Pays | Tag | Gain |
|---|---|---|
| AU | ©2024 | 12 % |
| BR | Smallcam 2025 | 11 % |
| CA | ©2025 | 11 % |
| CA | ©2024 | 19 % |
| CR | ©2025 | 18 % |
| CY | Smallcam 2024 | 18 % |
| ES | Blue 2025 | 16 % |
| ES | Blue 2024 | 16 % |
| FI | Smallcam 2025 | 18 % |
| FR | Blue 23 (NA) | 15 % |
| GB | Smallcam 2025 | 20 % |
| IT | Smallcam 2025 | 17 % |
| LU | Blue 2024 | 17 % |
| LV | ©2024 | 15 % |
| PE | ©2026 | 15 % |
| PT | Blue Car 2024 | 18 % |
| TR | Smallcam 2026 | 16 % |
| TR | Smallcam 2025 | 17 % |
| US | No Car 2024 | 12 % |
| US | Blue 2024 | 17 % |
| US | Black 2025 | 10 % |
| US | Black 2024 | 16 % |
| US | Black 2023 | 18 % |

Écartés pour non-discriminance (15) : `©2025` en AU, BD, BR, CL, GB, ZA ;
`©2024` au BR ; `©2026` en GB ; `Smallcam 2025` en BA ; `Smallcam 25` en FR ;
`Smallcam` en ZA ; `Blue Car 2022` et `Blue Car 2023` en DE ; `Brakelight` et
`Blue 2025` aux US.
