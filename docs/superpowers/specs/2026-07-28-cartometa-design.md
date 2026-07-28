# Cartometa — carte interactive des métas GeoGuessr

Date : 2026-07-28
Statut : validé, prêt pour la planification d'implémentation

## 1. Objectif

Un outil web où un joueur clique sur un point du globe et voit toutes les métas
applicables à cette zone, triées de la plus spécifique à la plus générale.

Une « méta » est un indice visuel exploitable en jeu — type de poteau, bollard,
marquage au sol, végétation, plaque d'immatriculation — valable sur une zone
géographique donnée.

Usage : révision hors partie, et consultation rapide en cours de partie.

### Critères de succès

- Clic → affichage en moins de 100 ms.
- Couverture initiale : au moins 300 métas sur au moins 20 pays.
- Erreur géographique de l'ordre de 10 km sur les frontières de zone.
- Ajouter un pays ne demande pas d'écrire de code.

### Hors périmètre v1

Compte utilisateur, synchronisation, favoris serveur. Mode quiz. Application
mobile native. Intégration en direct avec GeoGuessr. Édition manuelle des
sommets de polygone (voir §6.1).

## 2. Reconnaissance de la source

Toutes les affirmations de cette section ont été vérifiées le 2026-07-28 sur la
page Pologne réellement sauvegardée, pas supposées.

### 2.1 L'accès automatisé est fermé

`plonkit.net` renvoie **403** sur toute requête non-navigateur, y compris
`/sitemap.xml` — Cloudflare filtre. Son `robots.txt` interdit explicitement
`ClaudeBot`, et se termine par `User-agent: * / Disallow: /`, les seuls `Allow`
étant réservés à Googlebot, Bingbot et DuckDuckBot.

**Conséquence retenue :** aucun crawler ne sera écrit. Les pages sont
enregistrées à la main depuis le navigateur (`Ctrl+S` → « Page Web, complète »)
dans `input/`. Le composant 1 ne lit que ces fichiers locaux.

### 2.2 Structure d'une page pays

Chaque méta est un bloc autonome et régulier :

```html
<div id="1VXO" class="relative group/bk">
  <a href="https://maps.app.goo.gl/JmGQh1xdaQMBcnxZA">
    <img srcset="… orchards_004.webp 600w, … orchards_005.webp 1920w">
  </a>
  <p><strong>Orchards</strong> are mostly concentrated around the towns of Gróje…</p>
</div>
```

- L'attribut `id` est **l'identifiant stable fourni par le site** (celui du
  bouton « Copy link to this tip »). Il sert d'`id` de méta : déterministe,
  sans hachage.
- Titre = le `<strong>`. Description = le texte du `<p>`.
- Le `srcset` expose explicitement une variante **1920 px**.
- **14 métas sur 38 portent un lien Google Maps** vers le lieu de la photo.

### 2.3 La carte est un encart, pas une image séparée

Contrairement à l'hypothèse initiale, il n'existe pas de carte miniature par
méta. L'image est **composite** : photo Street View à gauche, **encart
cartographique en bas à droite**, à cadrage et échelle constants d'une méta à
l'autre. Toutes les images de méta partagent les mêmes dimensions
(1920×943, 1200×589, 900×442, 800×393, 600×295, 450×221).

À 1920 px, l'encart fait environ 545 px pour ~700 km de large, soit
**~1,3 km/pixel** — nettement mieux que les 200–400 px supposés dans la
spécification d'origine. La cible de 10 km est confortable.

L'encart est net et vectoriel : fond crème, frontières de voïvodies noires,
rivières bleues, contour blanc.

### 2.4 Les zones rouges ignorent l'administratif — confirmé

La méta `orchards` montre deux taches rouges arbitraires qui ne suivent aucune
limite de voïvodie, alors même que ces limites sont dessinées sur la carte.
L'approche « détecter la région administrative coloriée » reste écartée, cette
fois sur preuve.

### 2.5 Deux sémantiques de marqueur rouge

Découverte non prévue par la spécification d'origine :

- **Zone remplie** (`orchards`, `Poland-southern-hills`) → une aire.
- **Pin en goutte** (`Tatra_Mountains`) → un point. Un masque rouge naïf en
  ferait un polygone d'environ 50 km centré au-dessus du lieu réel, la position
  étant la pointe du pin et non le centre du blob. Erreur systématique.

### 2.6 Rouge parasite

La photo contient du rouge sans rapport (rose des vents rouge et blanche en bas
à gauche de `Tatra_Mountains`). Ce rouge est **hors de l'encart** : le
recadrage l'élimine, aucun filtrage sophistiqué n'est nécessaire.

### 2.7 Les liens Maps donnent les coordonnées gratuitement

Les deux formes de lien (`goo.gl/maps/…` et `maps.app.goo.gl/…`) répondent
encore en 302, et **l'URL de redirection contient les coordonnées** — la page
cible n'a pas besoin d'être chargée.

Vérifié : Tatra → `49.302333, 20.0088885` (Zakopane) ; Poznań →
`52.3989296, 16.9213161`. Les deux sont corrects.

### 2.8 Le typage par section — la simplification centrale

Les quatre `<h3>` de la page déterminent la nature géométrique de la méta :

| Section | Contenu | Encart | Géométrie |
|---|---|---|---|
| Step 1 — Identifying | bollards, poteaux, plaques, langue | aucun | polygone du pays entier |
| Step 2 — Regional | vergers, collines du sud, peinture de poteaux | zone rouge | polygone à tracer |
| Step 3 — Spotlight | Tatras, Gdańsk, Hel, Białystok, Szczecin, Poznań | pin rouge | point + rayon |
| Step 4 — Maps and resources | liens | — | ignoré |

**Le traitement d'image ne concerne que la Step 2**, soit une dizaine de métas
sur 38 pour la Pologne. La Step 1 ne demande aucun pixel, la Step 3 se réduit à
un point issu du lien Maps.

## 3. Architecture

Trois étages indépendants communiquant par fichiers, chacun relançable seul.

```
input/<Pays>.htm + <Pays>_files/   ← sauvegardes manuelles du navigateur
        ↓  [1] extractor
data/metas/<CC>.json               ← métas structurées, tier, coordonnées
        ↓  [2] pipeline
data/calib/<CC>.json               ← calibration pixel→WGS84, éditable
data/geo/<CC>.geojson              ← géométries, confiance, avertissements, statut
        ↓  [3] review / viewer
```

Le viewer doit fonctionner sur un jeu de données partiel — un seul pays importé
suffit.

### Choix techniques

- Étages 1 et 2 : Python, géré par `uv`. Dépendances : `selectolax` (parsing
  HTML tolérant), `Pillow`, `numpy`, `scikit-image` (contours par marching
  squares), `shapely` (géométrie et validité). Pas d'OpenCV — inutilement lourd
  pour ce besoin.
- Étage 3 : HTML et JavaScript statiques, Leaflet, sans étape de build.
- Formats intermédiaires ouverts et inspectables : JSON, GeoJSON, images.
- Tout seuil, tolérance ou palette est en fichier de configuration, jamais en
  constante dans le code.

**Risque identifié :** Python 3.14 est la version installée. Si des roues
binaires manquent pour `scikit-image` ou `shapely`, épingler le projet sur
Python 3.12 via `uv`.

## 4. Composant 1 — Extracteur

Ce n'est pas un scraper : il lit `input/`. Son seul accès réseau est la
résolution des liens Maps courts, chez Google et non chez Plonk It, mise en
cache sur disque pour n'être faite qu'une fois par lien.

### Sortie, par méta

| Champ | Description |
|---|---|
| `id` | attribut `id` du bloc, fourni par le site |
| `country` | code ISO 3166-1 alpha-2 |
| `tier` | `country`, `regional` ou `spot`, déduit du `<h3>` précédent |
| `title` | texte du `<strong>` |
| `description` | texte du `<p>` |
| `description_origin` | `imported` ou `rewritten` |
| `category` | poteaux / bollards / véhicule / végétation / signalisation / autre, inféré au mieux |
| `image` | chemin local de la variante la plus large du `srcset` |
| `maps_url` | lien Maps d'origine, si présent |
| `maps_latlon` | coordonnées résolues, si disponibles |
| `source_url` | URL d'origine reconstruite avec l'ancre de l'`id` |
| `extracted_at` | horodatage |

### Contraintes

- Idempotent : deux exécutions produisent le même fichier.
- Parsing tolérant : une anomalie de structure est signalée, elle ne fait pas
  échouer l'exécution.
- Résumé d'exécution : nombre de métas par pays et par tier, nombre sans image,
  nombre sans lien Maps, anomalies rencontrées.

### Note juridique

Textes et images de Plonk It sont protégés. Le projet est à **usage
personnel**. Chaque entrée conserve `source_url`, et `description_origin`
distingue une description importée d'une description réécrite, en vue d'une
éventuelle publication ultérieure.

**Le contenu copié n'est pas versionné.** `input/` et les images dérivées sont
placés en `.gitignore` : le dépôt contient le code, les calibrations et les
géométries — qui sont des données produites — mais jamais les textes ni les
photos de Plonk It.

## 5. Composant 2 — Pipeline image → géométrie

### Aiguillage par tier

- `country` → polygone Natural Earth 1:10m du pays, aucun traitement d'image.
- `spot` → point du lien Maps, entouré d'un cercle. Rayon par défaut selon la
  catégorie (ville ~25 km, massif ~50 km), ajustable à la revue. Si le lien
  Maps manque, la méta est mise en attente de décision humaine.
- `regional` → les quatre stages ci-dessous.

### Stage 0 — Extraction de l'encart

Localiser l'encart dans l'image composite par sa teinte crème sur fond blanc
dans la moitié droite, et recadrer. Élimine par construction tout rouge
parasite présent dans la photo.

### Stage 1 — Calibration, une fois par pays

Ajuster une transformation similaire — échelle en x, échelle en y, translation
— entre la silhouette crème de l'encart et le contour Natural Earth 1:10m du
pays, en maximisant l'IoU.

Sur l'étendue d'un seul pays, ignorer la projection réelle coûte de l'ordre du
kilomètre, négligeable devant la cible de 10 km.

Résultat écrit dans `data/calib/<CC>.json`, versionné et éditable à la main,
avec le **résidu d'ajustement**. Au-delà d'un seuil, le pays est signalé plutôt
que traité silencieusement.

### Stage 2 — Masque rouge

Conversion HSV, seuillage sur la teinte rouge en gérant le wrap-around autour
de 0°, puis ouverture et fermeture morphologiques contre le bruit et
l'anti-aliasing. Seuils en configuration.

### Stage 3 — Vectorisation

Composantes connexes, filtrage des surfaces négligeables, extraction des
contours, simplification Douglas-Peucker à tolérance réglable, gestion des
anneaux intérieurs, validation `shapely` avec `buffer(0)`, puis reprojection
par la calibration du Stage 1.

Enfin, **dilatation d'environ 3 km**, paramétrable, pour appliquer la règle : en
cas d'incertitude, un polygone légèrement trop large vaut mieux qu'un polygone
trop étroit. Une méta manquante pénalise plus le joueur qu'une méta affichée à
tort.

Sortie : `Polygon` ou `MultiPolygon` GeoJSON valide.

### Vérification automatique de justesse

Pour toute méta `regional` disposant aussi d'un lien Maps, vérifier que le
point tombe **à l'intérieur** du polygone généré.

C'est un contrôle objectif sur données réelles, sans jugement humain. Il
alimente le score de confiance et mesure directement le taux exigé au §7.

### Cas dégénérés — signaler, jamais produire un résultat faux en silence

- zone rouge touchant le bord de l'encart (zone tronquée) ;
- surface très faible (île, ville ponctuelle) ;
- composantes connexes disjointes nombreuses ;
- absence totale de rouge ;
- rouge couvrant la quasi-totalité du pays → utiliser le polygone du pays ;
- pays insulaire ou à territoires distants → la calibration peut échouer ;
- point Maps tombant hors du polygone généré ;
- résidu de calibration au-delà du seuil.

### Sortie, par méta

Géométrie, **score de confiance**, liste des avertissements déclenchés, et
statut parmi `auto`, `validé`, `corrigé`, `rejeté`.

Le score de confiance sert uniquement à **ordonner la file de revue** : les cas
les plus douteux en premier.

## 6. Composant 3 — Interfaces

### 6.1 Interface de revue

Elle écrit sur disque, donc un serveur local minimal en bibliothèque standard,
lancé par une commande, servant un écran unique, une méta à la fois.

- À gauche : l'image composite source, encart surligné.
- À droite : carte Leaflet portant le polygone généré, le contour du pays, et
  **le point Maps quand il existe**. Si le point tombe hors du polygone, le
  rejet est immédiat et sans réflexion.
- En bas : titre, description, avertissements.

Exigences :

- Clavier intégral : `A` valider, `R` rejeter, `Espace` passer, `U` annuler la
  dernière décision.
- File triée par confiance croissante.
- État persisté après chaque décision par écriture atomique ; reprise possible
  à tout moment.
- Compteur de progression visible.
- Objectif : **moins de 10 secondes par méta** en régime nominal.

**Édition manuelle des sommets — reportée, décision assumée.** C'est la
fonction la plus coûteuse du projet, et sa nécessité dépend d'un chiffre encore
inconnu : le taux de validation automatique. La v1 offre deux échappatoires
bien moins chères — un curseur de rayon pour les métas ponctuelles, et un rejet
qui renvoie vers une correction directe du GeoJSON, format ouvert et éditable.
Si la mesure sur la Pologne tombe sous les 70 %, on saura alors *quel* type de
correction est réellement nécessaire, au lieu de le deviner. Construire
l'éditeur de sommets d'abord, ce serait risquer de l'écrire pour dix métas.

### 6.2 Viewer public

- Carte mondiale zoomable, fond sobre et lisible.
- Clic ou tap sur un point → panneau listant toutes les métas dont la géométrie
  contient ce point.
- Tri par surface croissante, du plus spécifique au plus général.
- Chaque entrée : titre, catégorie, image, description, lien source. Le survol
  ou la sélection surligne la géométrie correspondante.
- Filtres par catégorie ; recherche textuelle sur titre et description.
- En portrait, le panneau devient une feuille glissante par-dessus la carte.

Contraintes techniques :

- **Déployable en statique**, par simple copie de dossier. Aucun serveur
  applicatif, aucune base de données.
- Recherche du point : filtre par bounding box puis test point-dans-polygone
  exact, en JavaScript. À quelques milliers de polygones cela tient largement
  sous la milliseconde ; **aucune librairie d'index spatial n'est justifiée**.
- Données scindées en deux fichiers : un léger avec textes et bounding boxes,
  chargé d'emblée, et un plus lourd avec les géométries complètes.

## 7. Critères d'acceptation

### Précision

Erreur cible de l'ordre de **10 km** sur les frontières de zone. En cas
d'incertitude, préférer un polygone légèrement trop large.

### Fonctionnel

- Un clic dans une zone connue retourne les métas attendues, y compris les
  métas nationales.
- Un clic en pleine mer ou dans un pays non couvert retourne une réponse vide
  explicite, sans erreur.
- Le viewer fonctionne avec un seul pays importé.

### Qualité de traitement

- Sur un échantillon de 30 métas de pays variés, au moins **70 % des polygones
  automatiques validés sans retouche**. En dessous, le pipeline est révisé.

  La Pologne seule ne compte qu'une dizaine de métas `regional` : ce critère ne
  peut donc être évalué qu'après l'ajout de deux ou trois pays. La verticale
  Pologne fournit une **mesure préliminaire** sur ses seules métas `regional` ;
  c'est elle qui décide de la suite, notamment de l'éditeur de sommets (§6.1).
- Aucune géométrie invalide produite : ni auto-intersection, ni anneau non
  fermé.
- Pour les métas `regional` disposant d'un lien Maps, le point tombe dans le
  polygone.

## 8. Méthode de travail

1. **Verticale d'abord** : la Pologne de bout en bout — extraction, géométries,
   revue, affichage — avant toute généralisation.
2. Valider chaque étage sur données réelles avant de passer au suivant.
3. Prioriser l'interface de revue **tôt** : elle sert aussi d'outil de
   diagnostic du pipeline.
4. Rendre configurable tout seuil, tolérance ou palette.
5. Documenter les hypothèses invalidées, pour éviter d'y revenir.

### Hypothèses déjà invalidées

- « Chaque méta a une carte miniature séparée » → faux, c'est un encart dans
  une image composite (§2.3).
- « Les images font 200–400 px, la précision est limitée par construction » →
  faux, une variante 1920 px existe, à ~1,3 km/pixel (§2.3).
- « Un scraper poli respectant robots.txt » → contradictoire, `robots.txt`
  interdit tout et Cloudflare renvoie 403 (§2.1).
- « Tout marqueur rouge est une zone » → faux, les pins ponctuels existent
  (§2.5).
- « Détecter la région administrative coloriée » → écarté sur preuve (§2.4).

### Livrables

- Code des trois composants, avec instructions de lancement.
- Fichiers de calibration par pays, versionnés et éditables.
- Un jeu de données d'exemple : la Pologne, complète, revue et validée.
- Un rapport court : ce qui fonctionne, taux de validation automatique
  constaté, limites connues, pays problématiques.
