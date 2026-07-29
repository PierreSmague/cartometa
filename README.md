# Cartometa

Carte interactive des métas GeoGuessr. On clique sur un point du globe, on voit
toutes les métas applicables, de la plus spécifique à la plus générale.

**Usage personnel.** Les textes et images viennent de [Plonk It](https://www.plonkit.net)
et ne sont pas versionnés (`input/`, `data/metas/` sont ignorés par git).

## Consulter la carte

Le viewer est statique mais lit ses données par `fetch`, donc il lui faut un
serveur HTTP — un double-clic sur `viewer/index.html` échouera (CORS sur
`file://`). Depuis la racine du dépôt :

```
python -m http.server 8010
```

puis <http://127.0.0.1:8010/viewer/>. `Ctrl+C` pour arrêter.

Clic sur la carte → panneau des métas triées par surface croissante.
Filtres par catégorie et recherche textuelle en haut du panneau.

Deux dépendances externes au moment de l'affichage : Leaflet et les tuiles de
fond, tous deux chargés depuis Internet. La carte ne fonctionne donc pas hors
connexion.

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

### 3. Générer les polygones

```
uv run cartometa-geo <CC>
```

Écrit `data/geo/<CC>.geojson`. Trois traitements selon la section d'origine de
la méta :

| Tier | Géométrie |
|---|---|
| `country` | silhouette Natural Earth du pays, aucun traitement d'image |
| `regional` | vectorisation de la zone rouge de l'encart cartographique |
| `spot` | disque autour des coordonnées du lien Maps |

Au premier passage sur un pays, une **calibration** pixel → WGS84 est ajustée
sur la silhouette et sauvegardée dans `data/calib/<CC>.json`. Elle est
réutilisée ensuite ; supprime le fichier pour la recalculer. Un IoU sous 0,90
déclenche un avertissement.

Les statuts de revue déjà attribués sont préservés entre deux exécutions.

Réglages dans `config/defaults.toml` : seuils de couleur, tolérance de
simplification, rayons par défaut des métas ponctuelles.

### 4. Revoir à la main

```
uv run cartometa-review <CC>
```

Sert une interface sur <http://127.0.0.1:8765> (écoute sur la boucle locale
uniquement). File triée par confiance croissante, cas douteux en premier.
Image source à gauche, polygone généré sur une vraie carte à droite.

| Touche | Action |
|---|---|
| `A` | valider |
| `R` | rejeter |
| `Espace` | passer |
| `U` | annuler la dernière décision |

Le point bleu, quand il est présent, est la **vérité terrain** : c'est la
position du lien Maps de la méta. S'il tombe hors du polygone, rejeter.

Pour les métas ponctuelles, le rayon est modifiable — c'est la correction la
plus fréquente. Chaque décision est écrite sur disque immédiatement, la session
est interruptible.

### 5. Publier vers le viewer

```
uv run cartometa-export <CC>
```

N'exporte que les métas `validé` et `corrigé`, vers `viewer/data/`.
`--include-auto` inclut aussi les non revues — l'outil affiche alors combien,
pour qu'une publication de données non validées ne passe pas inaperçue.

## Développement

```
uv sync
uv run pytest
```

86 tests. Aucun ne touche le réseau ; ceux marqués `real_data` sont sautés si
`input/` est absent.

## Où sont les choses

```
cartometa/extract/   HTML → métas structurées, résolution des liens Maps
cartometa/geo/       calibration, silhouette, vectorisation, export
cartometa/review/    serveur local de revue + interface clavier
viewer/              carte statique (Leaflet, sans build)
config/defaults.toml seuils et paramètres
data/calib/          calibrations par pays (versionnées)
data/geo/            polygones + statuts de revue (versionnés)
data/metas/          textes Plonk It (jamais versionnés, régénérables)
input/               pages sauvegardées (jamais versionnées)
docs/                spec, plan, rapport de la verticale Pologne
```

## État

Pologne : 37 métas revues, 33 publiées. Justesse automatique 8/8 sur les métas
disposant d'une vérité terrain, calibration à ~1,3 km/pixel, latence de requête
0,2–3,6 ms. Détail et limites dans [`docs/rapport-pologne.md`](docs/rapport-pologne.md).
