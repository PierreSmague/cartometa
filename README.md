# Cartometa

Carte interactive des métas GeoGuessr. On clique sur un point du globe, on voit
toutes les métas applicables, de la plus spécifique à la plus générale.

**Usage personnel.** Les textes et images viennent de [Plonk It](https://www.plonkit.net)
et ne sont pas versionnés (`input/`, `data/metas/` sont ignorés par git).

Le code est sous licence MIT (`LICENSE`) ; les données publiées (textes,
images, emprises) sont sous CC BY-NC-SA 4.0 (`LICENSE-DATA`) — ce sont deux
licences différentes, voir aussi `viewer/licence.html`.

## Consulter la carte

```
uv run cartometa-build
python -m http.server 8010 --directory dist
```

puis <http://127.0.0.1:8010/>. `Ctrl+C` pour arrêter.

Clic sur la carte → galerie des métas triées par surface croissante. Survol
d'une vignette → son emprise sur la carte. Clic → image pleine taille. Les
filtres se cumulent : catégorie, portée (régionale / nationale) et recherche
textuelle.

Coller un lien Google Street View ou Maps dans la barre de l'en-tête recentre
la carte sur le point et affiche ses métas. Un serveur statique ne sert pas
`/api/resolve`, donc les **liens raccourcis** (`maps.app.goo.gl`) échouent avec
la commande ci-dessus. Pour les tester en local, il faut le runtime Cloudflare :

```
npx wrangler pages dev dist
```

## Ajouter un pays

Quatre commandes, dans cet ordre. Toutes sont relançables sans dégât.

### 1. Capturer la page source

Plonk It bloque tout accès automatisé (`robots.txt` interdit tout, Cloudflare
répond 403). La capture est donc **manuelle** : ouvre la page du pays dans ton
navigateur, `Ctrl+S`, « page web complète », dans `input/`.

Ne jamais écrire de crawler pour ce site.

### 2. Extraire les métas

```
uv run cartometa-extract <pays>
```

Parse le HTML sauvegardé, en tire titre, description, catégorie, images et lien
Maps, et écrit `data/metas/<CC>.json`. Résout les liens Google Maps en
coordonnées (mises en cache dans `data/cache/`) — c'est le seul accès réseau,
avec le téléchargement Natural Earth.

Le code ISO du pays est déduit du slug via les noms Natural Earth
(`botswana` → `BW`) : aucun pays n'a besoin d'être déclaré dans le code. Si le
slug Plonk It ne correspond à aucun nom Natural Earth, la commande le dit et
demande `--country XX`.

Ajouter `--retry-failed-links` pour retenter les liens marqués irrésolvables.

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
| `E` | ajoute la silhouette du pays entier |
| `F` | rogne la zone aux frontières du pays — tout ce qui dépasse est retiré ; rappuyer annule le rognage |
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

`F` évite de suivre une côte au clic : on pose un rectangle large qui déborde
sur la mer et les voisins, puis on rogne. Le rognage reste actif pendant que
la zone se construit (les morceaux posés ensuite sont rognés aussi) et la
carte affiche dès lors le résultat rogné, c'est-à-dire exactement ce que `A`
enregistrera. Le calcul est fait par le serveur sur la silhouette Natural
Earth, jamais dans le navigateur.

Le point bleu, quand il est présent, est la **vérité terrain** : la position
du lien Maps de la méta.

`cartometa-review <CC> --all` rouvre toutes les métas, y compris celles déjà
tracées, avec leurs morceaux — pour repasser sur un pays quand une nouvelle
source donne mieux.

Le mode subdivisions télécharge au premier usage le jeu de données Natural
Earth admin-1 (41 Mo), puis en extrait les régions du pays dans
`data/cache/admin1/`. Les lancements suivants sont instantanés.

### 4. Publier

```
uv run cartometa-build
npx wrangler pages deploy dist --project-name cartometa --branch main
```

`--branch main` n'est pas optionnel : sans lui, `wrangler` déduit la branche du
dépôt git local, et tout ce qui n'est pas `main` part en *preview* sur une URL
`<branche>.cartometa.pages.dev` sans toucher au site. Le déploiement réussit,
mais `cartometa.com` reste sur la version précédente.

`cartometa-build` produit un `dist/` autonome et gitignoré : géométries
simplifiées et découpées par pays, images en deux tailles, empreintes de
contenu pour le cache. Les images sources vivant dans `input/`, non versionné,
le site ne peut être construit que localement.

`dist/` est rasé à chaque appel, mais **les images ne sont réencodées qu'une
fois**. Elles sont conservées dans `data/cache/images/` (gitignoré, ~230 Mo à
1922 emprises), indexées sur le contenu de la source et sur les réglages
d'encodage. Une publication qui n'ajoute que quelques métas prend donc une
trentaine de secondes au lieu de douze minutes. Changer une largeur ou la
qualité dans `cartometa/build/images.py` invalide le cache de lui-même. Le
supprimer est sans danger : le build suivant le reconstruit.

Options utiles : `--skip-images` pour itérer vite sur le code,
`--simplify-tolerance` pour ajuster la finesse des contours (défaut 0,01°,
plafonnée par la taille de chaque emprise).

### Fond de carte Google (facultatif)

```
uv run cartometa-build --google-key AIza...
```

Ajoute un sélecteur `OSM / Google` en coin de carte. **OpenStreetMap reste le
fond par défaut à chaque chargement**, et rien de Google n'est demandé — ni
script, ni carte instanciée — tant que le visiteur ne clique pas. Google
facturant à l'initialisation de carte, un visiteur qui reste sur OSM ne coûte
donc rien.

Sans `--google-key`, le sélecteur n'apparaît pas : un contributeur construit
le site en local sans clé et obtient un aperçu complet. Le build le signale
alors en fin de sortie, parce que l'oubli est silencieux côté site — la carte
s'affiche, seul le second fond manque.

À défaut d'option, la variable d'environnement `CARTOMETA_GOOGLE_KEY` est lue.
C'est la forme à préférer pour une machine qui publie : `dist/` n'étant pas
versionné, un build lancé pour tout autre motif (un correctif, une
optimisation) republierait sinon un site sans sélecteur sans que rien ne le
rappelle.

```
setx CARTOMETA_GOOGLE_KEY AIza...        # Windows, une fois pour toutes
export CARTOMETA_GOOGLE_KEY=AIza...     # shell POSIX
```

La clé n'est **jamais versionnée**. Elle sera
publique dans `data/manifest.json` du site livré — une clé de navigateur l'est
toujours — mais elle n'a pas à rester dans l'historique git après une
rotation. Deux protections à régler côté console Google Cloud, sans lesquelles
n'importe qui peut consommer ton quota : **restriction par référent HTTP** sur
tes domaines, et **plafond de quota journalier**.

Le greffon `viewer/googleMutant.js` est vendorisé
([Leaflet.GridLayer.GoogleMutant](https://gitlab.com/IvanSanchez/Leaflet.GridLayer.GoogleMutant/),
licence BEER-WARE, notice d'auteur conservée).

### Envoyer une méta vers Anki (facultatif)

Chaque méta ouverte en grand porte un bouton « Add to Anki » : il crée une
carte (image au recto ; emprise sur silhouette du pays, explication et lien
source au verso) dans le paquet choisi, via
[AnkiConnect](https://ankiweb.net/shared/info/2055492159).

Côté visiteur, trois conditions, expliquées aussi dans le guide replié
« Anki integration » que le site affiche quand Anki ne répond pas :
Anki ouvert avec AnkiConnect installé, l'origine du site ajoutée à
`webCorsOriginList` dans la config du module (`https://cartometa.com`, ou
`http://127.0.0.1:8010` en local), et la permission « réseau local » que
Chrome ≥ 142 demande au premier appel. Safari ne permet pas ce dialogue.

Deux notes pour le développement :

- AnkiConnect écoute sur le port 8765 — le même que `cartometa-review`.
  Anki ouvert pendant une session de tracé, l'un des deux ne démarrera pas.
- Le build publie dans chaque fichier pays la silhouette Natural Earth
  (`outline`), fond de la mini-carte. Pays inconnu du dataset ou dataset
  injoignable : le build passe outre en le signalant, et la mini-carte de ce
  pays se dessine sans fond.

## Développement

```
uv sync
uv run python -m pytest
```

`uv run pytest` échoue sur certaines machines Windows (stratégie de contrôle
d'applications, `os error 4551`) : ne pas « corriger » l'invocation ci-dessus
en le retirant, `python -m pytest` est la forme qui fonctionne partout.

216 tests. Aucun ne touche le réseau ; ceux marqués `real_data` sont sautés
seulement si aucun `data/geo/*.geojson` n'existe. Ces fichiers étant suivis
par git, ils sont toujours présents : tant qu'aucune emprise n'y a été
tracée, ces tests s'exécutent sur des fichiers vides et passent sans rien
vérifier.

## Où sont les choses

```
cartometa/build/     dataset, géométries, images, gabarits : cartometa-build
cartometa/extract/   HTML → métas structurées, résolution des liens Maps
cartometa/geo/       référentiel Natural Earth (pays, régions)
cartometa/review/    serveur local de revue + interface de tracé
viewer/              gabarits de la carte (Leaflet), assemblés par cartometa-build
functions/           seul code serveur : /api/resolve suit les liens Maps courts
data/geo/            emprises tracées + statut + morceaux (versionnées)
data/manual/         métas saisies à la main, textes et images (versionnées)
data/metas/          textes Plonk It (jamais versionnés, régénérables)
input/               pages sauvegardées (jamais versionnées)
docs/                specs, plans, guides de contribution
```

## État

Détection automatique retirée le 2026-07-30 : les emprises sont désormais
tracées à la main. Les géométries produites par l'ancien pipeline ont été
effacées et sont à refaire — elles restent consultables dans l'historique
git, de même que le rapport de mesures qui les accompagnait.
