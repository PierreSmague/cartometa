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

Le point bleu, quand il est présent, est la **vérité terrain** : la position
du lien Maps de la méta.

`cartometa-review <CC> --all` rouvre toutes les métas, y compris celles déjà
tracées, avec leurs morceaux — pour repasser sur un pays quand une nouvelle
source donne mieux.

Le mode subdivisions télécharge au premier usage le jeu de données Natural
Earth admin-1 (41 Mo), puis en extrait les régions du pays dans
`data/cache/admin1/`. Les lancements suivants sont instantanés.

### 4. Publier vers le viewer

```
uv run cartometa-export
```

Sans argument, exporte **tous** les pays présents dans `data/geo/` — un nouveau
pays entre dans le viewer dès qu'une de ses métas a été tracée, sans changer la
commande. Passer des codes (`cartometa-export PL`) restreint l'export.

N'exporte que les métas `validé`, vers `viewer/data/`.

## Développement

```
uv sync
uv run pytest
```

142 tests. Aucun ne touche le réseau ; ceux marqués `real_data` sont sautés
seulement si aucun `data/geo/*.geojson` n'existe. Ces fichiers étant suivis
par git, ils sont toujours présents : tant qu'aucune emprise n'y a été
tracée, ces tests s'exécutent sur des fichiers vides et passent sans rien
vérifier.

## Où sont les choses

```
cartometa/extract/   HTML → métas structurées, résolution des liens Maps
cartometa/geo/       référentiel Natural Earth (pays, régions) et export
cartometa/review/    serveur local de revue + interface de tracé
viewer/              carte statique (Leaflet, sans build)
data/geo/            emprises tracées + statut + morceaux (versionnées)
data/manual/         métas saisies à la main, textes et images (versionnées)
data/metas/          textes Plonk It (jamais versionnés, régénérables)
input/               pages sauvegardées (jamais versionnées)
docs/                specs, plans, rapports
```

## État

Détection automatique retirée le 2026-07-30 : les emprises sont désormais
tracées à la main. Les géométries produites par l'ancien pipeline ont été
effacées et sont à refaire — elles restent consultables dans l'historique
git. `docs/rapport-pologne.md` décrit le pipeline supprimé, conservé comme
trace historique.
