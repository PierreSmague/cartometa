# cartometa-extract-rmrg — extracteur pour les guides RMRG

Design validé le 2026-08-06.

## 1. Objectif

Importer les métas des guides RMRG (`rmrg.me`) dans le pipeline Cartometa
existant, à partir d'une page sauvegardée par navigateur — exactement comme
l'extracteur Plonk It. Première page cible : « Bangladesh GeoGuessr Guide -
RMRG.htm » (112 métas, canonique `https://rmrg.me/bangladesh/`).

RMRG est une seconde source pour des pays que Plonk It couvre déjà : le
Bangladesh a déjà `data/metas/BD.json` (44 métas Plonk It, toutes tracées).
Les deux sources doivent cohabiter sans se marcher dessus.

### Critères de succès

- `uv run cartometa-extract-rmrg bangladesh` produit
  `data/metas/BD-rmrg.json` avec les 112 métas, chacune avec catégorie,
  titre, description, lien Maps résolu, image et mini-carte SVG.
- La queue de revue du Bangladesh montre les métas RMRG (les Plonk It étant
  toutes décidées), avec la mini-carte RMRG affichée à côté de la photo.
- Un re-run de `cartometa-extract bangladesh` (Plonk It) ne touche pas aux
  métas RMRG, et réciproquement.
- Aucun changement de comportement pour les pays sans fichier `-rmrg.json`.

### Hors périmètre

- Publication de l'`overlay` sur le site public (champ de revue uniquement).
- Framework générique de « sources » : deux sites ne justifient pas une
  abstraction ; un troisième site copiera ce découpage.
- Résolution automatique du tracé depuis le SVG RMRG : le tracé reste manuel,
  le SVG n'est qu'une aide visuelle.

## 2. Reconnaissance de la source

Vérifié le 2026-08-06 sur la page Bangladesh réellement sauvegardée.

La structure RMRG est nettement plus régulière que celle de Plonk It :

- Des `div.category-section` dont le `h3.category-title` nomme la section :
  Landscape, Agriculture, Vegetation, Architecture, Infrastructure, Culture.
  Certaines sections ont des sous-sections `div.subcategory-section` avec un
  `h4.subcategory-title` (Wood Frames, Auto Rickshaws…).
- Chaque méta est un `div.meta-item` avec un id lisible et hiérarchique
  (`landscape/water-plots1`, `architecture/wood-frames/wood-frame-houses`)
  et un `data-item-slug` (`water-plots1`).
- Dans chaque bloc : un `a.image-link` dont le href est un lien
  `maps.app.goo.gl` ; une photo webp locale dans `.base-image img[src]` ;
  une mini-carte SVG dans `.svg-overlay-container img[src]` qui surligne la
  région concernée ; le texte dans `div.meta-description` (des `<strong>`
  en cours de phrase, jamais de titre).
- Les sections « Learnable Meta Maps » et « Contributors » ne contiennent
  aucun `.meta-item` : elles s'ignorent naturellement.
- Les fichiers SVG sauvegardés sont en réalité des `.svgz` : contenu gzip
  (magic `\x1f\x8b`), le navigateur a enregistré la réponse compressée
  telle quelle. Ils ne s'affichent pas tels quels dans un navigateur servi
  en local.
- Pas de tiers « Step 1/2/3 » : le guide est entièrement du regionguessing.
- 133 liens `maps.app.goo.gl` pour 112 blocs : quelques liens
  supplémentaires vivent dans le texte des descriptions.

## 3. Décisions de design

Quatre décisions structurantes, validées explicitement :

1. **Cohabitation par fichier séparé.** L'extracteur RMRG écrit
   `data/metas/<CC>-rmrg.json` ; il ne partage aucun fichier de sortie avec
   l'extracteur Plonk It. `CountryPaths` gagne une propriété `rmrg_metas` et
   `load_metas` lit importé + rmrg + manuel, dans cet ordre. C'est le seul
   point de contact avec le stockage : queue de revue et build voient les
   métas RMRG sans autre modification.
2. **Titre = slug humanisé.** `data-item-slug` → tirets remplacés par des
   espaces, chiffres finaux retirés, majuscule initiale : `water-plots1` →
   « Water plots », `alternating-brick-corners` → « Alternating brick
   corners ». Les slugs RMRG sont des noms descriptifs choisis par les
   auteurs — plus courts et plus stables qu'une première phrase.
3. **tier="regional" constant, catégorie depuis la section.** Tout RMRG est
   du regionguessing ; la section h3 donne la catégorie directement, sans
   passer par `infer_category` : `agriculture` → `vegetation` (la taxonomie
   range l'agriculture sous végétation), les cinq autres mappent 1:1
   (landscape, vegetation, architecture, infrastructure, culture). Section
   inconnue → `autre` + anomalie signalée.
4. **La mini-carte SVG est extraite et affichée dans la revue.** C'est
   littéralement la région que le relecteur trace à la main : la voir à
   côté de la photo change le confort du tracé. Nouveau champ optionnel
   `overlay` sur `MetaRecord`, affichage conditionnel dans le viewer de
   revue.

## 4. Le parser (`cartometa/extract/rmrg.py`)

`parse_rmrg_page(html, country, base_url) -> tuple[list[MetaRecord], list[str]]`,
miroir de `parse_page` Plonk It, avec selectolax.

Pour chaque `div.meta-item` sous un `div.category-section` :

- `id` : l'attribut `id` du bloc, tel quel. Unique par pays par
  construction ; tout le stockage aval (geo, categories.json, build) est
  scopé pays, donc la collision inter-pays (`landscape/banyan-trees` au
  Bangladesh et ailleurs) est sans effet. Les `/` dans l'id circulent en
  JSON et en query-param encodé : aucun chemin d'URL ne les reçoit.
- `country`, `tier="regional"`, `origin=ORIGIN_RMRG` (nouvelle constante
  dans `models.py`, à côté de `ORIGIN_PLONKIT`).
- `category` : depuis le h3 de la section englobante (mapping du §3.3).
- `description` : texte de `.meta-description`, blancs normalisés
  (même `_clean_text` que Plonk It).
- `title` : slug humanisé (§3.2).
- `maps_url` : href du `a.image-link` s'il matche le motif maps ;
  fallback : premier lien maps du bloc. Peut être `None`.
- `image` : src de l'img de `.base-image`, décodé (`unquote`). Pas de
  srcset chez RMRG.
- `source_url` : `{base_url}#{id}` — l'id du bloc est l'ancre native de la
  page.
- `overlay` : voir §5.

Anomalies signalées sans interrompre (liste retournée, comme Plonk It) :
bloc sans description, section inconnue, SVG illisible.

## 5. L'overlay SVG

Le src de l'img `.svg-overlay-container` pointe vers un fichier local du
dossier `_files`. À l'extraction :

- Si le fichier commence par le magic gzip `\x1f\x8b` : décompression vers
  un fichier frère suffixé `.extracted.svg` (ex. `water-plots1_8PNy.svg` →
  `water-plots1_8PNy.extracted.svg`). L'original — qui fait partie de la
  sauvegarde navigateur, non régénérable depuis le dépôt — n'est jamais
  modifié. Le sidecar est régénérable et vit sous `input/`, gitignoré et
  déjà servi par le serveur de revue (`ALLOWED_ROOT_PREFIXES`).
- Si le fichier est déjà du SVG en clair : référencé tel quel, pas de
  sidecar.
- Fichier absent ou illisible : `overlay=None` + anomalie ; l'extraction
  continue.

`MetaRecord.overlay : str | None = None`, chemin relatif à la racine du
projet comme `image`. Champ de revue uniquement : `build_dataset` ne le
publie pas.

## 6. La CLI (`cartometa/extract/rmrg_cli.py`)

Entrée console `cartometa-extract-rmrg` déclarée dans `pyproject.toml`.

- `cartometa-extract-rmrg bangladesh`, mêmes options que la CLI Plonk It :
  `--input`, `--data`, `--country` (sinon `resolve_country`, réutilisé tel
  quel), `--no-resolve`, `--retry-failed-links`, `--link-delay`. Pas de
  slug par défaut : contrairement à Plonk It, il n'y a pas de pays de
  référence évident.
- **Recherche de la page** : même normalisation que `_find_page`, restreinte
  aux fichiers dont le nom contient « RMRG » — sinon le slug `bangladesh`
  matcherait aussi « Bangladesh — Plonk It.htm » et échouerait pour
  ambiguïté. Symétriquement, la recherche Plonk It exclut désormais les
  fichiers RMRG (le nom « Bangladesh GeoGuessr Guide - RMRG » contient
  « bangladesh » : sans exclusion, c'est le re-run Plonk It qui devient
  ambigu).
- **Résolution Maps** : cache partagé `data/cache/maps_links.json`, même
  politesse (`_would_hit_network` + délai avant chaque vrai appel réseau).
- **Base URL** : `https://rmrg.me/{slug}/`.
- **Sortie** : `data/metas/<CC>-rmrg.json`, même format JSON que Plonk It.
  Résumé console par catégorie (le tier est constant), avec les mêmes
  compteurs sans-image / sans-coordonnées et la liste des anomalies.

### Factorisation

Les briques communes quittent `cli.py` pour un module partagé
(`cartometa/extract/common.py`) importé par les deux CLI : recherche de
page normalisée (paramétrée par un filtre), `_would_hit_network`, calcul du
chemin d'image relatif au projet, boucle de résolution des liens.
Comportement Plonk It strictement inchangé — les tests existants le
vérifient.

## 7. Stockage, revue, build

- `CountryPaths.rmrg_metas` → `data/metas/<CC>-rmrg.json` ;
  `load_metas` = importé + rmrg + manuel.
- `build_queue` expose `overlay` comme il expose `image` (préfixe `/`).
- Viewer de revue : `<img>` conditionnel à côté de la photo quand
  `overlay` est présent. Aucun autre changement d'UI.
- Build du site : aucun changement de code. Les métas RMRG tracées se
  publient comme les autres — le `scope` vient du tracé, la catégorie de la
  méta, les overrides `data/categories.json` s'appliquent (scopés pays).
- `.gitignore` : rien à faire, `data/metas/` couvre déjà `-rmrg.json` et
  `input/` couvre les sidecars.

## 8. Tests

- Parser : fragment HTML RMRG minimal embarqué dans le test — sections et
  sous-sections h4, catégorie depuis la section (y compris
  agriculture → vegetation et section inconnue → autre + anomalie), titre
  depuis le slug, lien maps depuis `image-link` et fallback description,
  bloc sans description, `source_url` avec ancre.
- Overlay : décompression gzip vers sidecar, SVG en clair référencé tel
  quel, fichier absent → anomalie. Sur fichiers temporaires, pas sur la
  vraie sauvegarde.
- Recherche de page : le slug `bangladesh` trouve la page RMRG côté RMRG,
  la page Plonk It côté Plonk It, sans ambiguïté dans les deux sens.
- `load_metas` : trois fichiers présents → concaténation dans l'ordre ;
  fichier rmrg absent → comportement identique à aujourd'hui.
- Non-régression : la suite existante passe inchangée après la
  factorisation de `common.py`.
