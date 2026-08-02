# Cartometa — site public

Spec de conception, 2026-08-02.

## 1. Objectif

Transformer Cartometa d'un viewer local en site web public, hébergé, consultable
par n'importe qui, et republiable en une commande à chaque fois que de nouvelles
métas sont tracées.

Ce document couvre le **jalon 1 : le site public en lecture seule**. L'outillage
pour contributeurs fait l'objet d'un jalon ultérieur et n'est pas traité ici.

## 2. Décisions cadrées

| Sujet | Décision |
|---|---|
| Licence du contenu | Plonk It publie sous CC BY-NC-SA 4.0. La rediffusion est donc autorisée, sous attribution, sans usage commercial, et avec partage à l'identique. |
| Licence du jeu de données publié | CC BY-NC-SA 4.0, emprises tracées à la main comprises. Assumé : un tiers peut les réutiliser. |
| Licence du code | MIT. Le ShareAlike porte sur le matériel et ses adaptations, pas sur le logiciel qui le traite. |
| Accès | Public, non restreint. |
| Hébergeur | Cloudflare Pages. |
| Publication | Artefact de build hors git, téléversé par `wrangler`. |
| Fond de carte | OSM standard, inchangé. |
| Interface | Moitié carte / moitié galerie, habillage clair neutre. |

## 3. Architecture

### 3.1 Source et artefact

`viewer/` reste la **source** : gabarit HTML, CSS, JS. Le dossier `dist/` est
l'**artefact** de build, gitignoré, produit par une commande unique.

`viewer/data/` disparaît du dépôt (`git rm --cached`), ce qui met fin à la
réécriture d'un blob de 40 Mo à chaque export. L'historique déjà constitué n'est
pas réécrit — hors périmètre.

### 3.2 Arborescence produite

```
dist/
  index.html                        non caché
  licence.html                      non caché
  app.<hash>.js                     immuable
  style.<hash>.css                  immuable
  _headers                          règles de cache Cloudflare
  data/
    manifest.json                   non caché — unique porte d'entrée
    index.<hash>.json               index global léger
    c/<CC>.<hash>.json              un fichier par pays
  img/<CC>/<id>.<hash>.webp         vignette et pleine taille
```

Tous les noms de fichiers hormis `index.html`, `licence.html` et
`manifest.json` portent une empreinte de leur contenu : les 8 premiers
caractères hexadécimaux du SHA-256 des octets écrits.

### 3.3 Commande de build

`cartometa-build` **remplace** `cartometa-export`. Elle enchaîne :

1. lecture de `data/geo/*.geojson` et fusion des deux sources de métas
   (import Plonk It et saisie manuelle), en ne retenant que le statut `validé` ;
2. simplification des géométries puis arrondi des coordonnées (dans cet ordre,
   cf. §6) ;
3. découpage par pays et construction de l'index global ;
4. redimensionnement et réencodage des images ;
5. copie des gabarits statiques et calcul des empreintes ;
6. écriture du `manifest.json` et du `_headers` ;
7. résumé chiffré à l'écran.

Drapeaux : `--out` (défaut `dist`), `--data` (défaut `data`),
`--simplify-tolerance` (défaut `0.01`), `--skip-images` (itération rapide sur
le code sans repayer l'encodage), et une liste optionnelle de codes pays.

La commande est relançable sans dégât et réécrit intégralement sa sortie.

## 4. Modèle de données

### 4.1 `manifest.json`

```json
{
  "version": "<empreinte globale du build>",
  "built_at": "2026-08-02T21:40:00Z",
  "meta_count": 1679,
  "image_base": "img/",
  "index": "index.<hash>.json",
  "countries": { "PL": { "file": "c/PL.<hash>.json", "count": 42 } }
}
```

`image_base` est **lu depuis le manifeste et jamais codé en dur** : c'est la
parade qui permettra de déplacer les images vers un stockage objet sans toucher
à l'application (voir §9).

### 4.2 Index global

Une entrée par méta, réduite au minimum nécessaire au filtre par bbox, et
stockée en tableau plutôt qu'en objet pour éviter de répéter les clés :

```json
[["eF7M","LB",35.5108,33.8803,35.5158,33.8838,0.000018], ...]
```

Soit `[id, pays, minLon, minLat, maxLon, maxLat, surface]`, trié par surface
croissante. Mesuré : ~90 Ko bruts pour 1679 métas, ~25 Ko transférés.

### 4.3 Fichier par pays

```json
{
  "metas": { "<id>": { "title": "...", "description": "...",
                       "category": "...", "source_url": "...",
                       "thumb": "IL/<id>.<hash>.t.webp",
                       "full":  "IL/<id>.<hash>.f.webp" } },
  "geometries": { "<id>": { "type": "Polygon", "coordinates": [...] } }
}
```

## 5. Chargement et requête

Le viewer actuel charge 41 Mo au démarrage et teste toutes les métas à chaque
clic. Le nouveau fonctionnement :

1. **Au démarrage** : `manifest.json` puis l'index global. ~30 Ko au total.
2. **Au clic** : filtre par bbox en mémoire sur l'index → ensemble de pays
   candidats → téléchargement des fichiers pays manquants (mémorisés pour la
   session) → test point-dans-polygone précis → affichage trié par surface
   croissante.
3. **Au survol d'une vignette** : surlignage de l'emprise, déjà en mémoire
   puisqu'elle a servi au test.

Pendant l'attente d'un fichier pays, la galerie affiche des cases grises. Les
clics suivants dans le même pays sont instantanés.

Aucun préchargement anticipé dans ce jalon : à évaluer à l'usage.

## 6. Simplification des géométries

Deux traitements, dans cet ordre : simplification de Douglas-Peucker
(`shapely.simplify`, `preserve_topology=True`) puis arrondi des coordonnées à
5 décimales (~1 m).

Mesures à la tolérance par défaut de 0,01° (~1,1 km) :

| pays | brut | simplifié | transféré (gzip) |
|---|---|---|---|
| ID | 8,28 Mo | 2,59 Mo | 854 Ko |
| JP | 3,76 Mo | 1,24 Mo | 351 Ko |
| IN | 3,73 Mo | 1,00 Mo | 322 Ko |
| TR | 2,41 Mo | 0,70 Mo | 54 Ko |
| PL | 0,66 Mo | 0,19 Mo | 8 Ko |

Écart de surface constaté : moins de 0,1 %. L'arrondi seul ne rapporte que 8 % ;
le gain vient de la simplification.

**Vérifications automatiques** (pour chaque géométrie simplifiée) :

- distance de Hausdorff à l'original ≤ tolérance ;
- écart de surface ≤ 0,5 % ;
- géométrie valide et non vide.

Un critère fondé sur les points de vérité terrain (coordonnées du lien Maps) a
été envisagé puis **écarté** : Plonk It place parfois ce lien à visée
d'illustration, hors de la zone décrite, si bien qu'un tel test échouerait sur
des données correctes.

La tolérance reste réglable en ligne de commande pour ajustement à l'usage.

## 7. Images

Deux tailles par méta, en webp qualité 78, mesurées sur un échantillon de 40 :

| | par image |
|---|---|
| source 1920 px | 151 Ko |
| vignette 600 px | 20 Ko |
| pleine 1400 px | 76 Ko |
| **total par méta** | **96 Ko** |

La vignette alimente la galerie, la pleine taille l'agrandissement au clic. Le
choix est laissé au navigateur par `srcset`. 1400 px est un plancher : ce sont
des montages à plusieurs panneaux annotés, illisibles en dessous.

Les filigranes Google présents dans les captures ne sont **jamais rognés**,
seulement redimensionnés.

Les images sources vivent dans `input/`, non versionné et local à la machine de
l'auteur : elles ne peuvent donc être produites que localement, jamais par
l'hébergeur. C'est ce qui impose le modèle « artefact de build ».

## 8. Cache

Fichier `_headers` :

```
/data/manifest.json
  Cache-Control: no-cache
/index.html
  Cache-Control: no-cache
/licence.html
  Cache-Control: no-cache
/data/*
  Cache-Control: public, max-age=31536000, immutable
/img/*
  Cache-Control: public, max-age=31536000, immutable
/*.js
  Cache-Control: public, max-age=31536000, immutable
/*.css
  Cache-Control: public, max-age=31536000, immutable
```

L'empreinte étant calculée **par fichier**, ajouter un pays ne renouvelle que le
fichier de ce pays : les visiteurs gardent les 43 autres en cache.

## 9. Mise à l'échelle

Le facteur limitant n'est ni le volume ni la vitesse, mais le **nombre de
fichiers accepté par déploiement Cloudflare Pages, soit 20 000**. À deux images
par méta, le plafond est atteint vers 10 000 métas — **au total, tous pays
confondus**, et non par pays. À titre de repère, le pays le mieux fourni
aujourd'hui compte 100 métas.

| métas | images | fichiers | index transféré |
|---|---|---|---|
| 1 679 | 0,16 Go | 3 358 | ~25 Ko |
| 5 000 | 0,48 Go | 10 000 | ~75 Ko |
| 10 000 | 0,96 Go | 20 000 | ~150 Ko |

Les géométries ne participent pas à cette montée en charge : le découpage par
pays fait qu'un clic télécharge un pays, quel que soit le total.

Parade prévue et sans coût immédiat : `image_base` vit dans le manifeste. Le
jour où le compteur approche, les images basculent vers un stockage objet
(Cloudflare R2 : pas de limite de fichiers, 10 Go gratuits, sortie réseau
gratuite) et seule cette valeur change.

`wrangler` ne téléverse que les fichiers dont le contenu a changé : le premier
déploiement envoie ~160 Mo, les suivants quelques mégaoctets.

## 10. Interface

Structure retenue : **moitié carte, moitié galerie**, au motif que dans une méta
GeoGuessr l'image porte l'information et le texte la légende. Habillage clair
neutre, accent `#c1283a` — celui déjà utilisé pour le surlignage.

- **En-tête** : nom, sous-titre, compteurs (métas, pays).
- **Carte** : 46 % de la largeur, tuiles OSM standard, attribution native.
- **Galerie** : grille de deux colonnes, vignette en 16/8, code pays et titre
  tronqué à deux lignes. Ordre : surface croissante.
- **Barre de filtres** : pastilles de catégorie et champ de recherche, portant
  sur les résultats du clic courant.
- **Pied de page** : `Textes et images © 2021-2026 Plonk It, CC BY-NC-SA 4.0 ·
  Imagery © Google · Fond © OpenStreetMap`, plus le lien vers `/licence.html`.
- **État d'accueil** : carte du monde et carte d'introduction expliquant
  l'interaction, avec les compteurs.
- **Agrandissement** : clic sur une vignette → image pleine taille en surcouche,
  titre complet, lien « source » vers l'ancre Plonk It.
- **URL partageable** : position et zoom dans le fragment (`#lat,lon,z`),
  restaurés au chargement.

L'habillage sombre est écarté pour ce jalon, mais l'interface et le fond de
carte étant indépendants, une bascule sombre conservant les tuiles OSM claires
reste possible plus tard par simples variables CSS.

## 11. Attribution et licences

- Bandeau d'attribution permanent en pied de page.
- Page `/licence.html` : mention CC BY-NC-SA 4.0 avec lien vers le deed,
  `© 2021-2026 Plonk It`, indication que le matériel a été modifié (découpage,
  ajout d'emprises), distinction entre ce qui vient de Plonk It et ce qui vient
  du projet, note sur l'imagerie Google sous-jacente, et adresse de contact pour
  une demande de retrait : `psmague@gmail.com`, en `mailto:`. Adresse
  personnelle et non professionnelle, délibérément : publier un projet non
  commercial sous une adresse d'entreprise brouillerait le critère « NC ».
- `LICENSE` (MIT, code) et `LICENSE-DATA` (CC BY-NC-SA 4.0, données) à la racine.
- `CONTRIBUTING.md` : les contributions sont publiées sous CC BY-NC-SA 4.0.
- Lien « source » par méta vers l'ancre Plonk It — déjà présent dans les données.

## 12. Tests

Le dépôt compte 142 tests, aucun ne touchant le réseau. Cette propriété est
conservée. Nouveaux tests :

- découpage : chaque méta exportée apparaît dans exactement un fichier pays, et
  l'index global référence exactement les mêmes identifiants ;
- simplification : les trois vérifications du §6, sur des géométries synthétiques
  et sur les données réelles quand elles sont présentes ;
- empreintes : deux builds sur des données identiques produisent les mêmes noms
  de fichiers ; modifier un seul pays ne change que le nom de ce pays ;
- manifeste : tout fichier référencé existe, tout fichier produit est référencé ;
- images : redimensionnement et réencodage sur des images synthétiques, sans
  dépassement de la largeur cible ;
- `_headers` : présence des règles et cohérence avec l'arborescence produite.

## 13. Périmètre

**Dans le jalon** : découpage par pays, simplification, chargement paresseux,
images à deux tailles, cache par empreinte, attribution et pages de licence,
interface complète en clair, état d'accueil, agrandissement, URL partageable,
sortie de `viewer/data/` du dépôt.

**Hors jalon, explicitement** : adaptation mobile, recherche globale sur
l'ensemble des métas, page par pays, bascule sombre, changement de fournisseur
de tuiles, réécriture de l'historique git, et tout l'outillage pour
contributeurs.

Conséquence assumée de l'absence d'adaptation mobile : sur un téléphone, la
mise en page en deux colonnes restera à l'étroit. Le site est conçu pour le
grand écran dans ce jalon.

**Reporté au lendemain** : le déploiement lui-même, y compris la création du
compte Cloudflare et le nom de domaine.

## 14. Critères d'acceptation

1. `cartometa-build` produit un `dist/` servi tel quel par un serveur statique.
2. Le chargement initial transfère moins de 100 Ko hors tuiles de carte.
3. Un clic dans le pays le plus lourd transfère moins de 1 Mo, une seule fois
   par session.
4. Aucune image cassée : tout chemin d'image du `dist/` pointe vers un fichier
   existant.
5. Les trois vérifications de simplification passent sur les données réelles.
6. Le bandeau d'attribution est visible sur toutes les pages, et
   `/licence.html` est atteignable.
7. La suite de tests passe, sans accès réseau.
8. `git status` reste propre après un build : `dist/` est ignoré.
