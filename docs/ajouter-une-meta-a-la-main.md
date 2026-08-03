# Ajouter une méta à la main

Fiche pour un nouveau contributeur, en partant de zéro : de l'installation
jusqu'à la pull request. Compter ~20 min pour la première méta, ~2 min pour
les suivantes.

Une méta manuelle, c'est **cinq choses** :

| | |
|---|---|
| un titre | court, ce qu'on voit |
| une description | ce que ça permet de déduire |
| une catégorie | parmi six, imposées |
| une image *(facultative)* | la capture qui montre l'indice |
| **une emprise** | la zone du globe où la méta s'applique — tracée à la souris |

L'emprise est la seule partie qui ne se saisit pas au clavier, et c'est celle
qui a de la valeur : une méta sans emprise n'est jamais publiée.

---

## 1. Installer, une fois

Il faut **git**, **Python ≥ 3.14** et **[uv](https://docs.astral.sh/uv/)**.
`uv` installe Python tout seul si besoin.

```
git clone https://github.com/PierreSmague/cartometa.git
cd cartometa
uv sync
```

Vérification :

```
uv run python -m pytest
```

Tout doit passer. N'écris pas `uv run pytest` : sur certaines machines
Windows une stratégie de contrôle d'applications le fait échouer
(`os error 4551`). `python -m pytest` marche partout.

Rien d'autre à installer : pas de Node, pas de compte Cloudflare. La
publication du site est faite par le mainteneur.

---

## 2. Ouvrir l'interface de tracé

```
uv run cartometa-review FR
```

`FR` est le code **ISO 3166-1 alpha-2** du pays, tel que Natural Earth le
connaît (`FR`, `BW`, `KR`…). La casse est libre, il est mis en majuscules.

Puis <http://127.0.0.1:8765> dans le navigateur. Le serveur n'écoute que sur
la boucle locale.

Le pays n'a besoin **de rien** au préalable : aucun texte importé, aucun
fichier existant. Une file vide est un point de départ valide — c'est
exactement le cas « partir de zéro ». Les fichiers sont créés à la première
sauvegarde.

Deux téléchargements ont lieu au premier usage, une seule fois pour toujours,
dans `data/cache/` :

- la silhouette des pays (Natural Earth admin-0), au premier cadrage ;
- les régions administratives (admin-1, **41 Mo**), au premier appui sur `S`.

`Ctrl+C` dans le terminal arrête le serveur. Tout est déjà enregistré sur le
disque au fur et à mesure : il n'y a pas de « sauvegarder avant de quitter ».

---

## 3. Saisir la méta

Appuie sur `N` (le focus doit être sur la page, pas dans un champ). Le
formulaire s'ouvre.

| Champ | Règle |
|---|---|
| **Titre** | obligatoire |
| **Description** | obligatoire |
| **Catégorie** | `bollards`, `poteaux`, `vehicule`, `vegetation`, `signalisation`, `autre` — pas d'autre valeur |
| **Source (URL)** | facultatif ; laissé vide, aucun lien ne s'affiche sur le site |
| **Image** | facultative : `Ctrl+V` pour coller une capture, ou glisse un fichier sur le cadre pointillé |

La catégorie **se devine toute seule** pendant que tu tapes le titre et la
description. Dès que tu en choisis une dans la liste, l'inférence se tait
définitivement : un choix explicite n'est jamais écrasé.

Contraintes sur l'image : **PNG, JPEG, WEBP ou GIF**, **8 Mo maximum**. Une
capture d'écran normale est très en dessous. Si l'image est refusée, la méta
est quand même créée (le message le dit) — tu pourras la compléter plus tard
en éditant `data/manual/<CC>/metas.json`.

`Créer` enregistre. `Échap` ou `Annuler` ferme sans rien écrire.

La méta créée **passe immédiatement en tête de file** : tu la traces tout de
suite, tant que tu as la source sous les yeux.

### Bien rédiger

- **Titre** : ce que l'œil voit, pas la conclusion. « Bollard blanc à bande
  rouge », pas « On est au Portugal ».
- **Description** : autoportante. Le lecteur du site voit la vignette et le
  texte, rien d'autre — ni le pays ni le contexte de ta session.
- **Image** : recadre sur l'indice. Une capture Street View pleine largeur
  où le poteau fait douze pixels n'apprend rien.
- **Portée** : une méta = une zone. Si l'indice vaut pour trois régions
  disjointes avec des variantes, ce sont souvent trois métas.

---

## 4. Tracer l'emprise

C'est le cœur du travail. La carte est à droite, la source à gauche.

| Touche | Action |
|---|---|
| `D` | **rectangle** — deux clics posent un morceau |
| `C` | **contour libre** — clics successifs ; fermeture en repassant sur le premier sommet, ou par `Entrée` |
| `S` | **subdivisions** — chaque clic ajoute/retire la région administrative sous le curseur |
| `E` | ajoute la **silhouette du pays entier** |
| `F` | **rogne** la zone aux frontières du pays ; rappuyer annule le rognage |
| `Retour arrière` | retire le dernier morceau, ou le dernier sommet d'un contour en cours |
| `Échap` | sort du mode de dessin sans rien effacer |
| `0` | vide la zone en cours |
| `A` | **enregistre** |
| `R` | **rejette** la méta |
| `Espace` / `Maj+Espace` | méta suivante / précédente |
| `U` | annule la dernière décision |
| `N` | nouvelle méta manuelle |

Les modes sont **collants** : après un rectangle posé, poser le suivant ne
demande aucune touche.

Une emprise est **l'union de ses morceaux** — deux rectangles disjoints,
trois régions, un contour libre plus le pays entier. Mélange librement.

`F` est le raccourci qui évite de suivre une côte au clic : pose un grand
rectangle qui déborde sur la mer et les voisins, puis rogne. Le rognage reste
actif pendant que la zone se construit, et la carte affiche dès lors le
résultat rogné — c'est-à-dire **exactement ce que `A` enregistrera**. Le
calcul est fait par le serveur sur la silhouette Natural Earth, jamais dans
le navigateur.

Le **point bleu**, quand il est là, est la vérité terrain : la position du
lien Maps de la méta. Une méta saisie à la main n'en a pas — la carte se
cadre alors sur le pays.

### Le tracé décide de la portée — attention

Le filtre « national / régional » du site est déduit **du tracé seul**, pas
d'un champ à cocher :

- emprise faite du **seul** morceau « pays entier » (`E`) → **national** ;
- **tout le reste**, y compris un pays rogné ou complété → **régional**.

Donc : si la méta vaut pour tout le pays, appuie sur `E` et rien d'autre.
N'ajoute pas un rectangle « pour être sûr » — il la ferait basculer en
régional.

`A` sur une zone vide refuse d'enregistrer et le dit. `R` sert aux métas qui
n'ont pas lieu d'être publiées : elles restent dans les fichiers, marquées
`rejeté`, et ne sortent jamais dans le site.

---

## 5. Ce qui a été écrit sur le disque

Pour un pays `FR`, après une méta créée et tracée :

```
data/manual/FR/metas.json          titre, description, catégorie, source
data/manual/FR/images/man-xxxx.png ton image
data/geo/FR.geojson                l'emprise, son statut, ses morceaux
```

Ton identifiant est de la forme `man-xxxx` (quatre caractères hexadécimaux).
Le préfixe `man-` rend toute collision impossible avec les identifiants
importés de Plonk It.

**Ces trois chemins sont versionnés par git** — c'est ta contribution, elle
est irremplaçable. À l'inverse, `input/`, `data/metas/`, `data/cache/` et
`dist/` sont ignorés : ne cherche pas à les committer.

`data/geo/FR.geojson` garde les *morceaux* tels que tu les as posés, pas
seulement la géométrie finale. C'est ce qui permet de rouvrir une emprise et
d'en retirer un morceau sans tout redessiner :

```
uv run cartometa-review FR --all
```

rouvre **toutes** les métas du pays, y compris celles déjà tracées ou
rejetées, avec leurs morceaux. Sans `--all`, la file ne contient que ce qui
reste à décider.

---

## 6. Vérifier dans le vrai site

**Toujours avec le code de ton pays.** `cartometa-build` sans argument
échoue sur un clone frais, et c'est normal — voir l'encadré juste après.

```
uv run cartometa-build FR
python -m http.server 8010 --directory dist
```

puis <http://127.0.0.1:8010/>. Clique dans ta zone : ta méta doit apparaître
dans la galerie, avec son image et sa description, et réagir aux filtres de
catégorie et de portée.

### Ton aperçu ne contient que tes métas — c'est normal

Le dépôt versionne **les emprises** (`data/geo/`, 45 pays, 1710 emprises)
mais **pas les textes** Plonk It qui vont avec (`data/metas/` est gitignoré,
usage personnel). Un clone frais a donc les contours de 45 pays et le texte
d'aucun.

Deux conséquences, toutes deux attendues :

- `uv run cartometa-build` **sans argument** parcourt les 45 pays et
  s'arrête sur le premier, avec le message
  *« AE : 18 emprise(s) versionnée(s), mais aucun texte de méta »*.
  Ce n'est pas une panne et tu n'as rien cassé. Donne le code de ton pays.
- `uv run cartometa-build FR` construit un site qui ne contient **que** tes
  métas à toi. Si tu ajoutes une méta à un pays déjà rempli (`AE`), l'aperçu
  affichera ta seule méta et pas les 18 autres : leurs textes sont absents de
  ton clone. Le site publié, lui, les aura toutes — le mainteneur construit
  depuis une copie complète.

Rien de tout cela n'affecte ta contribution : ce que tu livres, ce sont les
emprises et les textes manuels, pas le `dist/`.

Options utiles : `--skip-images` saute le réencodage (beaucoup plus rapide si
seul le tracé t'intéresse), `--simplify-tolerance` ajuste la finesse des
contours (défaut 0,01°).

Ne lance jamais **deux builds en parallèle** : le dossier `dist/` est effacé
en début de build, une collision tronque la sortie en silence.

Les liens Google Maps **raccourcis** (`maps.app.goo.gl`) collés dans la barre
de l'en-tête échouent avec ce serveur statique : leur résolution demande le
runtime Cloudflare (`npx wrangler pages dev dist`). Sans intérêt pour la
saisie de métas.

---

## 7. Proposer la contribution

```
git switch -c meta-fr-bollards
git add data/manual/FR data/geo/FR.geojson
git commit -m "feat: trois metas manuelles pour la France"
```

puis une pull request. Un commit ne doit contenir **que** `data/manual/**` et
`data/geo/*.geojson` — si `git status` montre autre chose, quelque chose ne
va pas.

**Licence.** En proposant une contribution, tu acceptes qu'elle soit publiée
sous **CC BY-NC-SA 4.0**, comme le reste des données du projet. C'est une
obligation de la licence de la source, pas un choix. Le code, lui, reste sous
MIT.

**Ne copie pas d'image dont tu n'as pas le droit de disposer.** Une capture
Street View que tu as prise toi-même, oui. Une image récupérée sur un site
tiers sans licence compatible, non.

Et, règle absolue du projet : **ne jamais écrire de crawler pour
plonkit.net**. Leur `robots.txt` interdit tout, et Cloudflare répond 403. Les
pages sources se capturent à la main, une par une, avec `Ctrl+S`.

---

## Pannes courantes

| Symptôme | Cause et remède |
|---|---|
| `uv run pytest` → `os error 4551` | Stratégie Windows. Utiliser `uv run python -m pytest`. |
| « Cadrage impossible » / `pays introuvable dans Natural Earth` | Le code ISO n'existe pas dans le jeu admin-0. Vérifier l'alpha-2. |
| « téléchargement admin-1 impossible » | Le jeu de 41 Mo n'a pas pu être récupéré. Vérifier le réseau et rappuyer sur `S`. |
| « Aucun morceau posé : rien à enregistrer » | `A` sur une zone vide. Poser au moins un morceau. |
| « format d'image non accepté » | PNG, JPEG, WEBP, GIF uniquement. |
| « image trop lourde » | Plafond de 8 Mo. Recadrer ou réenregistrer en JPEG. |
| « Méta créée, mais image refusée » | La méta existe, seule l'image manque. La compléter dans `data/manual/<CC>/metas.json`, champ `image`. |
| La file est vide au démarrage | Normal pour un pays neuf. Appuyer sur `N`. |
| `AE : … emprise(s) versionnée(s), mais aucun texte de méta` | `cartometa-build` a été lancé **sans code pays** sur un clone frais. Attendu. Relancer `uv run cartometa-build <TON_CODE>`. |

---

## Aide-mémoire

```
uv sync                          # une fois
uv run cartometa-review FR       # N → saisir, D/C/S/E/F → tracer, A → enregistrer
uv run cartometa-build FR        # vérifier
python -m http.server 8010 --directory dist
git add data/manual/FR data/geo/FR.geojson
```
