# Plan d'implémentation — bouton « Add to Anki »

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Depuis la loupe du viewer (méta affichée en grand), un bouton « Add to Anki » crée dans le paquet choisi une carte Anki : image de la méta au recto ; mini-carte de l'emprise sur le contour du pays, explication complète et lien source au verso.

**Architecture :** Le viewer parle à AnkiConnect (module Anki exposant une API HTTP sur `http://127.0.0.1:8765`) directement en `fetch` depuis le navigateur. Toute la logique vit dans un nouveau fichier autonome `viewer/anki.js`, couplé à `app.js` par un seul événement DOM (`cartometa:loupe`) — jamais par import, parce que le build empreinte chaque fichier JS séparément. Côté Python, une seule extension : `cartometa-build` publie dans chaque fichier pays une clé `outline` (silhouette Natural Earth simplifiée), dont la mini-carte a besoin comme fond.

**Tech stack :** JS vanilla (viewer), canvas 2D pour la mini-carte, AnkiConnect API v6, Python/shapely côté build, pytest.

## Contraintes globales

- Ne jamais lancer `uv run pytest` : sur cette machine c'est `uv run python -m pytest` (voir README, « os error 4551 »).
- Aucun test ne doit toucher le réseau. La silhouette Natural Earth est donc **injectée** dans `build_dataset` (paramètre `outline_de`) et **monkeypatchée** dans les tests de `build_site`.
- Style du dépôt : identifiants et commentaires en **français**, textes visibles du site en **anglais**. Les commentaires expliquent le *pourquoi*, pas le *quoi* — imiter la densité des fichiers existants.
- `viewer/app.js` ne doit rien connaître d'Anki ; `viewer/anki.js` ne doit toucher ni à la carte Leaflet ni à la galerie. Seul lien : les événements `cartometa:loupe` et `cartometa:loupe-fermee`.
- Pas d'en-tête `Content-Type` sur les requêtes vers AnkiConnect : la requête reste « simple » et évite le préversement CORS.
- Ne PAS annoter le `fetch` avec `targetAddressSpace` : `127.0.0.1` est un littéral loopback, Chrome le détecte seul (Local Network Access, Chrome ≥ 142) ; la valeur de l'option n'est pas stabilisée entre versions.
- Commits fréquents, un par tâche minimum, messages en français comme l'historique (`feat:`, `fix:`, `chore:`).

## Rappels de contexte pour un exécutant sans mémoire du projet

- Build complet local : `uv run cartometa-build` (écrit `dist/`), servir avec `python -m http.server 8010 --directory dist`.
- Un fichier pays publié a la forme `{"metas": {id: {...}}, "geometries": {empreinte: geojson}}` ; chaque méta y porte `title`, `description`, `category`, `scope`, `source_url`, `geom` (empreinte de sa géométrie), et `thumb`/`full` (chemins image relatifs à `image_base`) — `thumb`/`full` absents quand la méta n'a pas d'image.
- La loupe est ouverte par `ouvrirLoupe(meta)` dans `viewer/app.js` ; `meta` y contient en plus `id` et `code` (pays).
- Le dataset Natural Earth admin-0 vit dans `data/cache/ne_10m_admin_0_countries.geojson` (déjà présent sur la machine du mainteneur ; téléchargé au premier usage sinon). Accès par `country_geometry(iso_a2, cache_dir)` de `cartometa/geo/reference.py`, qui renvoie une géométrie shapely et lève `KeyError` si le pays est absent.
- AnkiConnect : requête POST JSON `{action, version: 6, params}` ; réponse `{result, error}`. Le port 8765 est aussi celui de `cartometa-review` — ne pas s'étonner si l'un des deux ne démarre pas quand l'autre tourne.

---

### Tâche 1 : `outline` dans `build_dataset` (injection, sans réseau)

**Files:**
- Modify: `cartometa/build/dataset.py`
- Test: `tests/test_build_dataset.py`

**Interfaces:**
- Produces: `build_dataset(data_dir, countries, tolerance=DEFAULT_TOLERANCE, outline_de=None)` — `outline_de: Callable[[str], dict | None] | None`. Quand il est fourni et renvoie une géométrie GeoJSON (dict), le fichier pays gagne une clé de premier niveau `"outline"` contenant cette géométrie simplifiée par `simplify_geometry(contour, tolerance)`. Quand il vaut `None` ou renvoie `None`, la clé est absente.

- [ ] **Étape 1 : test qui échoue**

Dans `tests/test_build_dataset.py`, à la suite des tests existants (réutiliser le helper `_ecrire_pays` déjà présent dans ce fichier) :

```python
def _contour_carre(pays: str) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [0.0, 0.0], [6.0, 0.0], [6.0, 6.0], [0.0, 6.0], [0.0, 0.0],
    ]]}


def test_le_contour_du_pays_est_publie_quand_il_est_fourni(tmp_path):
    """La mini-carte des cartes Anki dessine l'emprise sur la silhouette du
    pays : sans `outline` dans le fichier pays, le front n'a aucun fond à
    tracer."""
    _ecrire_pays(tmp_path / "data", "PL", [("pl1", "validé", 1.0)])

    jeu = build_dataset(tmp_path / "data", ["PL"], outline_de=_contour_carre)

    contour = jeu.countries["PL"]["outline"]
    assert contour["type"] == "Polygon"


def test_sans_fournisseur_de_contour_la_cle_est_absente(tmp_path):
    """L'absence de clé (et non une valeur nulle) est le contrat avec le
    front, qui teste `pays.outline` en vérité booléenne."""
    _ecrire_pays(tmp_path / "data", "PL", [("pl1", "validé", 1.0)])

    jeu = build_dataset(tmp_path / "data", ["PL"])

    assert "outline" not in jeu.countries["PL"]


def test_un_fournisseur_qui_renvoie_none_n_ecrit_pas_de_contour(tmp_path):
    """`None` est la valeur de repli du fournisseur (pays absent de Natural
    Earth, dataset injoignable) : le pays se publie quand même, sans fond."""
    _ecrire_pays(tmp_path / "data", "PL", [("pl1", "validé", 1.0)])

    jeu = build_dataset(tmp_path / "data", ["PL"], outline_de=lambda pays: None)

    assert "outline" not in jeu.countries["PL"]
```

- [ ] **Étape 2 : vérifier l'échec**

Run : `uv run python -m pytest tests/test_build_dataset.py -k contour -v`
Attendu : 2 FAIL (`TypeError: build_dataset() got an unexpected keyword argument 'outline_de'` / `KeyError: 'outline'`), le test « sans fournisseur » passe déjà.

- [ ] **Étape 3 : implémentation**

Dans `cartometa/build/dataset.py` :

1. Ajouter en tête : `from typing import Callable`.
2. Étendre la signature :

```python
def build_dataset(
    data_dir: Path,
    countries: list[str],
    tolerance: float = DEFAULT_TOLERANCE,
    outline_de: Callable[[str], dict | None] | None = None,
) -> Dataset:
```

3. Juste avant le `if entree_pays["geometries"]:` final de la boucle pays, insérer :

```python
        if entree_pays["geometries"] and outline_de is not None:
            # Silhouette du pays, fond de la mini-carte des cartes Anki.
            # Injectée plutôt qu'importée : le dataset Natural Earth vient du
            # réseau, et ni cette fonction ni ses tests ne doivent y toucher.
            contour = outline_de(pays)
            if contour is not None:
                entree_pays["outline"] = simplify_geometry(contour, tolerance)
```

4. Compléter la docstring de `build_dataset` d'une ligne sur `outline_de`.

- [ ] **Étape 4 : vérifier que tout passe**

Run : `uv run python -m pytest tests/test_build_dataset.py -v`
Attendu : tous PASS.

- [ ] **Étape 5 : commit**

```bash
git add cartometa/build/dataset.py tests/test_build_dataset.py
git commit -m "feat: contour de pays optionnel dans les fichiers publies"
```

---

### Tâche 2 : câblage Natural Earth dans `build_site`

**Files:**
- Modify: `cartometa/build/site.py`
- Test: `tests/test_build_site.py`

**Interfaces:**
- Consumes: `build_dataset(..., outline_de=...)` (tâche 1) ; `country_geometry(iso_a2, cache_dir)` de `cartometa.geo.reference`.
- Produces: chaque `dist/data/h/c/<CC>.<hash>.json` contient `"outline"` quand Natural Earth connaît le pays ; le build **réussit sans** `outline` quand le pays est inconnu (`KeyError`) ou le dataset injoignable (`OSError`), avec un avertissement imprimé.

- [ ] **Étape 1 : tests qui échouent**

Dans `tests/test_build_site.py` (le fixture existant crée `projet / "data"` et `projet / "viewer"` ; s'y référer pour les noms exacts — les tests ci-dessous suivent le motif des tests voisins qui appellent `build_site(projet / "data", dist, projet / "viewer", ["PL"])` puis relisent le fichier pays via le manifeste) :

```python
def _fichier_pays(dist: Path, code: str) -> dict:
    manifeste = json.loads((dist / "data" / "manifest.json").read_text("utf-8"))
    relatif = manifeste["countries"][code]["file"]
    return json.loads((dist / "data" / relatif).read_text("utf-8"))


def test_le_contour_natural_earth_est_publie(projet, monkeypatch):
    """Le build branche `country_geometry` sur `build_dataset` : c'est le seul
    endroit où les deux se rencontrent, donc le seul test qui le prouve."""
    from shapely.geometry import box

    monkeypatch.setattr(
        "cartometa.build.site.country_geometry",
        lambda code, cache_dir: box(0.0, 0.0, 5.0, 5.0),
    )
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert _fichier_pays(dist, "PL")["outline"]["type"] == "Polygon"


def test_un_pays_inconnu_de_natural_earth_se_publie_sans_contour(projet, monkeypatch):
    """`country_geometry` lève KeyError pour un code hors dataset : la
    mini-carte perd son fond, jamais le pays sa publication."""
    def _introuvable(code, cache_dir):
        raise KeyError(code)

    monkeypatch.setattr("cartometa.build.site.country_geometry", _introuvable)
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert "outline" not in _fichier_pays(dist, "PL")


def test_natural_earth_injoignable_ne_casse_pas_le_build(projet, monkeypatch):
    """Un clone frais construit hors ligne n'a pas le dataset en cache : le
    telechargement echoue en OSError et le site doit sortir quand meme."""
    def _hors_ligne(code, cache_dir):
        raise OSError("réseau coupé")

    monkeypatch.setattr("cartometa.build.site.country_geometry", _hors_ligne)
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert "outline" not in _fichier_pays(dist, "PL")
```

Si le fixture du fichier ne s'appelle pas `projet`, reprendre son vrai nom ; si un helper équivalent à `_fichier_pays` existe déjà, l'utiliser.

- [ ] **Étape 2 : vérifier l'échec**

Run : `uv run python -m pytest tests/test_build_site.py -k contour -v` (et `-k natural` pour les deux autres)
Attendu : FAIL — `AttributeError: ... has no attribute 'country_geometry'` (le symbole n'est pas encore importé dans `site.py`).

- [ ] **Étape 3 : implémentation**

Dans `cartometa/build/site.py` :

1. Imports : `from shapely.geometry import mapping` et `from cartometa.geo.reference import country_geometry`, plus `from typing import Callable` (compléter la ligne `typing` existante).
2. Ajouter, au niveau module :

```python
def _fabrique_contours(data_dir: Path) -> Callable[[str], dict | None]:
    """Fournisseur de silhouettes pays pour `build_dataset`.

    Trois issues, jamais d'échec de build : la silhouette (cas normal), None
    pour un pays hors Natural Earth (KeyError), None pour tous les pays dès
    la première panne d'accès au dataset (OSError : hors ligne sans cache,
    disque). La panne est mémorisée pour ne pas retenter — et râler — une
    fois par pays.
    """
    panne = False

    def contour_de(pays: str) -> dict | None:
        nonlocal panne
        if panne:
            return None
        try:
            return mapping(country_geometry(pays, data_dir / "cache"))
        except KeyError:
            print(f"  ! {pays} absent de Natural Earth : mini-carte sans fond")
            return None
        except OSError as erreur:
            panne = True
            print(f"  ! Natural Earth indisponible ({erreur}) : "
                  f"mini-cartes sans fond de pays")
            return None

    return contour_de
```

3. Dans `build_site`, remplacer l'appel existant par :

```python
    jeu = build_dataset(
        data_dir, countries, tolerance, outline_de=_fabrique_contours(data_dir)
    )
```

Note : `mapping()` renvoie des tuples ; `_dumps` les sérialise sans problème et `simplify_geometry` (tâche 1) repasse tout en listes.

- [ ] **Étape 4 : vérifier que tout passe**

Run : `uv run python -m pytest tests/test_build_site.py -v`
Attendu : tous PASS (les tests existants ne fournissent pas de cache Natural Earth : vérifier qu'aucun ne tente le réseau — le repli `OSError` doit les couvrir, sinon monkeypatcher au niveau du fixture).

**Attention :** si des tests existants de `test_build_site.py` (ou `test_build_cli.py`) échouent parce que `country_geometry` tente réellement de télécharger le dataset (pas de cache dans `tmp_path`), le repli `OSError` de `_fabrique_contours` doit les rattraper — `urllib` lève `URLError`, sous-classe d'`OSError`. Si un environnement de test a du réseau, le téléchargement de 25 Mo serait pire qu'un échec : dans ce cas ajouter un fixture `autouse` qui monkeypatche `cartometa.build.site.country_geometry` pour lever `OSError`, et en faire le comportement par défaut du fichier de test.

- [ ] **Étape 5 : run complet**

Run : `uv run python -m pytest`
Attendu : tous PASS, aucun accès réseau.

- [ ] **Étape 6 : commit**

```bash
git add cartometa/build/site.py tests/test_build_site.py
git commit -m "feat: silhouettes Natural Earth publiees dans les fichiers pays"
```

---

### Tâche 3 : `anki.js` publié comme actif empreinté

**Files:**
- Create: `viewer/anki.js` (stub, rempli en tâches 5–6)
- Modify: `cartometa/build/site.py` (`ACTIFS_STATIQUES`)
- Modify: `viewer/index.html` (balise script)
- Test: `tests/test_build_site.py` (fixture viewer)

**Interfaces:**
- Produces: marqueur `__ANKI_JS__` substitué dans les gabarits ; `dist/anki.<hash>.js` publié ; `verifier_integrite` le contrôle automatiquement (elle dérive d'`ACTIFS_STATIQUES`).

- [ ] **Étape 1 : créer le stub**

`viewer/anki.js` :

```js
// Pont entre la loupe et Anki via AnkiConnect. Rempli par les tâches
// suivantes ; publié dès maintenant pour que le câblage du build (empreinte,
// substitution, intégrité) soit en place et testé.
```

- [ ] **Étape 2 : déclarer l'actif**

Dans `ACTIFS_STATIQUES` (`cartometa/build/site.py`), après l'entrée `("app.js", "__JS__")` :

```python
    ("anki.js", "__ANKI_JS__"),
```

Le commentaire au-dessus de la liste le dit : copie, substitution et intégrité en dérivent — rien d'autre à faire côté build.

- [ ] **Étape 3 : la balise script**

Dans `viewer/index.html`, sous la ligne `<script defer type="module" src="__JS__"></script>` :

```html
  <script defer type="module" src="__ANKI_JS__"></script>
```

- [ ] **Étape 4 : le fixture de test**

Dans le fixture viewer de `tests/test_build_site.py` (là où `app.js` factice est écrit) :

```python
    (viewer / "anki.js").write_text("/* anki */", "utf-8")
```

- [ ] **Étape 5 : vérifier**

Run : `uv run python -m pytest tests/test_build_site.py tests/test_build_cli.py -v`
Attendu : tous PASS. Si `test_build_cli.py` fabrique son propre viewer factice, y ajouter `anki.js` de la même façon.

- [ ] **Étape 6 : build réel**

Run : `uv run cartometa-build --skip-images`
Attendu : sortie normale, `dist/anki.*.js` existe, `dist/index.html` ne contient plus `__ANKI_JS__`.

- [ ] **Étape 7 : commit**

```bash
git add viewer/anki.js viewer/index.html cartometa/build/site.py tests/test_build_site.py
git commit -m "chore: anki.js publie et empreinte comme les autres actifs"
```

---

### Tâche 4 : gabarit de la loupe, événements, CSS

**Files:**
- Modify: `viewer/index.html` (bloc `#loupe`)
- Modify: `viewer/app.js` (`ouvrirLoupe`, `fermerLoupe`)
- Modify: `viewer/style.css`

**Interfaces:**
- Produces: événement `cartometa:loupe` avec `detail = { meta, pays, imageUrl }` où `pays` est l'entrée `etat.pays.get(meta.code)` (donc `{metas, geometries, outline?}`) et `imageUrl` l'URL **absolue** de l'image pleine taille, ou `null` sans image. Événement `cartometa:loupe-fermee` sans détail. IDs DOM : `#anki-ajouter`, `#anki-etat`, `#anki-panneau`, `#anki-paquets`, `#anki-confirmer`, `#anki-guide` — consommés tels quels par la tâche 5.

- [ ] **Étape 1 : le gabarit**

Dans `viewer/index.html`, remplacer le bloc `#loupe` par :

```html
  <div id="loupe" hidden>
    <button id="loupe-fermer" aria-label="Close">×</button>
    <img id="loupe-image" alt="">
    <p id="loupe-texte"></p>
    <div id="anki-zone">
      <button id="anki-ajouter" type="button" hidden>Add to Anki</button>
      <span id="anki-etat" role="status" aria-live="polite"></span>
      <div id="anki-panneau" hidden>
        <select id="anki-paquets" aria-label="Anki deck"></select>
        <button id="anki-confirmer" type="button">Add</button>
      </div>
      <!-- Replié derrière un simple <summary> : la plupart des joueurs ne se
           servent pas d'Anki, le guide ne doit exister qu'au moment où le
           bouton échoue. -->
      <details id="anki-guide" hidden>
        <summary>Anki integration</summary>
        <ol>
          <li>Install <a href="https://apps.ankiweb.net/" target="_blank" rel="noopener">Anki</a>
              and the <a href="https://ankiweb.net/shared/info/2055492159" target="_blank"
              rel="noopener">AnkiConnect</a> add-on (code <code>2055492159</code>).</li>
          <li>In Anki: Tools &rarr; Add-ons &rarr; AnkiConnect &rarr; Config, add
              <code>"https://cartometa.com"</code> to <code>webCorsOriginList</code>.</li>
          <li>Restart Anki, keep it open, and click the button again. Allow the
              browser&rsquo;s local-network permission if it asks.</li>
        </ol>
        <p>Works in Chrome, Edge and Firefox. Safari does not let pages talk to
           local apps.</p>
      </details>
    </div>
  </div>
```

- [ ] **Étape 2 : les événements dans `app.js`**

À la fin d'`ouvrirLoupe(meta)`, juste avant `loupe.hidden = false;` :

```js
  // Tout ce que le module Anki doit savoir passe par cet événement : app.js
  // ne connaît pas Anki, anki.js ne connaît ni la carte ni la galerie. L'URL
  // d'image est absolue parce qu'elle quitte la page — c'est Anki (le
  // logiciel) qui la téléchargera, pas ce navigateur.
  document.dispatchEvent(new CustomEvent('cartometa:loupe', {
    detail: {
      meta,
      pays: etat.pays.get(meta.code),
      imageUrl: meta.full ? new URL(urlImage(meta.full), location.href).href : null,
    },
  }));
```

Dans `fermerLoupe()`, après `document.getElementById('loupe-image').src = '';` :

```js
  document.dispatchEvent(new Event('cartometa:loupe-fermee'));
```

- [ ] **Étape 3 : le CSS**

À la fin de `viewer/style.css` :

```css
/* --- Intégration Anki (dans la loupe) ------------------------------------ */
#anki-zone {
  color: #f2f2ee;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  max-width: 80ch;
}
#anki-zone button {
  font: inherit;
  padding: 5px 12px;
  border: 1px solid #f2f2ee;
  border-radius: var(--rayon);
  background: none;
  color: #f2f2ee;
  cursor: pointer;
}
#anki-zone button:disabled { opacity: 0.55; cursor: default; }
#anki-panneau { display: flex; gap: 8px; align-items: center; }
#anki-paquets { font: inherit; max-width: 32ch; }
#anki-guide { text-align: left; }
#anki-guide summary { cursor: pointer; text-align: center; }
#anki-guide a { color: #f2f2ee; }
#anki-guide code { font-size: 12px; }
```

- [ ] **Étape 4 : vérifier à l'œil**

Run : `uv run cartometa-build --skip-images` puis `python -m http.server 8010 --directory dist` (arrière-plan), ouvrir `http://127.0.0.1:8010/`, cliquer un point couvert, ouvrir une méta en grand.
Attendu : la loupe s'affiche comme avant ; le bouton « Add to Anki » n'apparaît **pas encore** (le stub `anki.js` ne le révèle pas) ; aucune erreur console. `Échap` ferme toujours la loupe.

Contrainte : `--skip-images` laisse `thumb`/`full` absents — pour un test visuel complet il faut un build avec images (plus long). Pour cette étape, l'absence d'erreur console et la mise en page suffisent.

- [ ] **Étape 5 : commit**

```bash
git add viewer/index.html viewer/app.js viewer/style.css
git commit -m "feat: la loupe expose la meta courante et le gabarit Anki"
```

---

### Tâche 5 : client AnkiConnect, choix du paquet, guide

**Files:**
- Modify: `viewer/anki.js` (remplace le stub)

**Interfaces:**
- Consumes: événements et IDs DOM de la tâche 4.
- Produces: fonctions internes `anki(action, params)`, `cleMeta(detail)`, `reinitialiser()` ; les fonctions `construireNote(detail, paquet)` et `assurerModele()` sont appelées ici mais **définies en tâche 6** — jusqu'à la tâche 6, en poser des versions provisoires qui lèvent `new Error('pas encore implémenté')`.

- [ ] **Étape 1 : écrire le module**

Contenu complet de `viewer/anki.js` :

```js
// Pont entre la loupe et Anki, via AnkiConnect (module Anki qui expose une
// API HTTP locale). Fichier délibérément autonome : app.js ne publie que
// l'événement `cartometa:loupe`, et rien ici ne touche à la carte ni à la
// galerie. Les deux fichiers sont empreintés séparément par le build — un
// import de l'un vers l'autre casserait au renommage, l'événement non.

const ANKI_URL = 'http://127.0.0.1:8765';
const MODELE = 'Cartometa';
const CLE_PAQUET = 'anki-paquet';

const bouton = document.getElementById('anki-ajouter');
const etatAnki = document.getElementById('anki-etat');
const panneau = document.getElementById('anki-panneau');
const selecteur = document.getElementById('anki-paquets');
const confirmer = document.getElementById('anki-confirmer');
const guide = document.getElementById('anki-guide');

// Détail du dernier `cartometa:loupe`. Chaque gestionnaire asynchrone en
// garde sa propre référence et vérifie au retour qu'elle est toujours la
// courante : le visiteur peut changer de méta pendant qu'une requête vole.
let courant = null;

async function anki(action, params = {}) {
  // Pas d'en-tête Content-Type : la requête reste « simple » au sens CORS et
  // s'épargne le préversement. AnkiConnect lit le corps quoi qu'il en soit.
  const reponse = await fetch(ANKI_URL, {
    method: 'POST',
    body: JSON.stringify({ action, version: 6, params }),
  });
  const charge = await reponse.json();
  if (charge.error) throw new Error(charge.error);
  return charge.result;
}

function cleMeta(detail) {
  // L'id d'une méta n'est unique que dans son pays : la clé publiée dans le
  // champ MetaId — et cherchée pour la détection de doublon — porte les deux.
  return `${detail.meta.code}-${detail.meta.id}`;
}

function reinitialiser() {
  // La méta sans image n'a pas de recto possible : pas de bouton du tout,
  // plutôt qu'un bouton qui fabriquerait une carte invalide.
  bouton.hidden = !courant?.imageUrl;
  bouton.disabled = false;
  bouton.textContent = 'Add to Anki';
  etatAnki.textContent = '';
  panneau.hidden = true;
  guide.hidden = true;
  guide.open = false;
}

document.addEventListener('cartometa:loupe', (evenement) => {
  courant = evenement.detail;
  reinitialiser();
});

document.addEventListener('cartometa:loupe-fermee', () => {
  courant = null;
});

bouton.addEventListener('click', async () => {
  const detail = courant;
  bouton.disabled = true;
  etatAnki.textContent = '…';
  let paquets;
  let doublons;
  try {
    const [noms, modeles] = await Promise.all([
      anki('deckNames'),
      anki('modelNames'),
    ]);
    paquets = noms;
    // Chercher dans un type de note qui n'existe pas encore est une erreur
    // de recherche Anki, pas un résultat vide : ne poser la question qu'une
    // fois le modèle créé par un premier ajout.
    doublons = modeles.includes(MODELE)
      ? await anki('findNotes', { query: `"note:${MODELE}" "MetaId:${cleMeta(detail)}"` })
      : [];
  } catch (erreur) {
    // Anki fermé, module absent, origine non autorisée, permission réseau
    // refusée : indistinguables d'ici, et la réponse est la même — le guide.
    if (courant !== detail) return;
    etatAnki.textContent = "Anki isn't responding.";
    guide.hidden = false;
    bouton.disabled = false;
    return;
  }
  if (courant !== detail) return;
  etatAnki.textContent = '';
  if (doublons.length) {
    bouton.textContent = 'Already in Anki';
    return; // bouton laissé désactivé : il n'y a rien de plus à faire
  }
  const options = [...paquets].sort().map((nom) => new Option(nom, nom));
  selecteur.replaceChildren(...options);
  const memorise = lirePaquetMemorise();
  if (memorise && paquets.includes(memorise)) selecteur.value = memorise;
  panneau.hidden = false;
});

confirmer.addEventListener('click', async () => {
  const detail = courant;
  const paquet = selecteur.value;
  confirmer.disabled = true;
  etatAnki.textContent = 'Adding…';
  try {
    await assurerModele();
    await anki('addNote', { note: construireNote(detail, paquet) });
  } catch (erreur) {
    if (courant !== detail) return;
    confirmer.disabled = false;
    // Distinct du guide : ici AnkiConnect répond, c'est l'ajout lui-même qui
    // a échoué (paquet supprimé entre-temps, image introuvable…). Le message
    // d'Anki est plus utile qu'une paraphrase.
    etatAnki.textContent = `Could not add the card: ${erreur.message}`;
    return;
  }
  if (courant !== detail) return;
  memoriserPaquet(paquet);
  confirmer.disabled = false;
  panneau.hidden = true;
  etatAnki.textContent = '';
  bouton.textContent = '✓ Added';
});

// localStorage peut être indisponible (navigation privée, réglages) : le
// souvenir du dernier paquet est un confort, jamais une condition.
function lirePaquetMemorise() {
  try {
    return localStorage.getItem(CLE_PAQUET);
  } catch {
    return null;
  }
}

function memoriserPaquet(paquet) {
  try {
    localStorage.setItem(CLE_PAQUET, paquet);
  } catch {
    // tant pis pour le souvenir
  }
}

// --- Provisoire : remplacé par la tâche 6 ----------------------------------

async function assurerModele() {
  throw new Error('pas encore implémenté');
}

function construireNote(detail, paquet) {
  throw new Error('pas encore implémenté');
}
```

- [ ] **Étape 2 : vérifier le flux sans Anki**

Run : `uv run cartometa-build --skip-images`, servir, ouvrir une méta en grand **sans** Anki lancé.
Attendu : le bouton n'apparaît pas (pas de `full` avec `--skip-images`) — refaire le test après un build complet (`uv run cartometa-build`) : le bouton apparaît, son clic affiche « Anki isn't responding. » et déplie l'accès au guide « Anki integration ». Aucune erreur console non gérée.

- [ ] **Étape 3 : vérifier le flux avec Anki**

Anki ouvert avec AnkiConnect installé et `webCorsOriginList` contenant `"http://127.0.0.1:8010"` et `"http://localhost:8010"` (Tools → Add-ons → AnkiConnect → Config, puis redémarrer Anki).
Attendu : le clic liste les paquets réels, le dernier choisi est présélectionné au second usage ; « Add » affiche « Could not add the card: pas encore implémenté » (comportement attendu à ce stade).

- [ ] **Étape 4 : commit**

```bash
git add viewer/anki.js
git commit -m "feat: dialogue AnkiConnect, choix du paquet et guide replie"
```

---

### Tâche 6 : mini-carte canvas et création de la note

**Files:**
- Modify: `viewer/anki.js` (remplacer la section « Provisoire »)

**Interfaces:**
- Consumes: `detail.pays.geometries[detail.meta.geom]` (emprise GeoJSON), `detail.pays.outline` (silhouette, possiblement absente), `detail.imageUrl`.
- Produces: note AnkiConnect complète ; modèle `Cartometa` dont le **premier champ est `MetaId`** — jamais vide et unique, c'est lui que le contrôle de doublon d'Anki regarde, et un premier champ vide ferait refuser la note.

- [ ] **Étape 1 : remplacer la section provisoire**

Supprimer les deux fonctions provisoires et coller à leur place :

```js
// --- Modèle et note ---------------------------------------------------------

async function assurerModele() {
  const modeles = await anki('modelNames');
  if (modeles.includes(MODELE)) return;
  // MetaId en premier champ, à dessein : Anki exige un premier champ non
  // vide et fonde dessus son contrôle de doublon. L'image, elle, n'est
  // remplie par AnkiConnect qu'au moment de l'ajout.
  await anki('createModel', {
    modelName: MODELE,
    inOrderFields: ['MetaId', 'Image', 'RegionMap', 'Explanation', 'Source'],
    css: [
      '.card { font-family: system-ui, sans-serif; font-size: 18px;',
      '  text-align: center; color: #1c1c1c; background: #fff; }',
      'img { max-width: 100%; }',
    ].join('\n'),
    cardTemplates: [{
      Name: 'Meta',
      Front: '{{Image}}',
      Back: '{{FrontSide}}<hr id="answer">{{RegionMap}}'
        + '<p>{{Explanation}}</p><p>{{Source}}</p>',
    }],
  });
}

// Les champs d'une note Anki sont du HTML : tout texte du dataset passe par
// ici avant d'y entrer. Même raison que textContent côté galerie — les
// textes viennent d'un HTML tiers.
function echapper(texte) {
  const boite = document.createElement('div');
  boite.textContent = texte ?? '';
  return boite.innerHTML;
}

function construireNote(detail, paquet) {
  const { meta, pays } = detail;
  const cle = cleMeta(detail);
  const note = {
    deckName: paquet,
    modelName: MODELE,
    fields: {
      MetaId: cle,
      Image: '',
      RegionMap: '',
      Explanation: echapper(meta.description),
      // Facultative : une méta saisie à la main n'a pas toujours de page
      // d'origine à citer.
      Source: meta.source_url
        ? `<a href="${echapper(meta.source_url)}">Plonk It</a>`
        : '',
    },
    options: { allowDuplicate: false },
    tags: ['cartometa', meta.code],
    // `url` et non un blob : c'est Anki (le logiciel de bureau) qui
    // télécharge l'image depuis le site et la range dans ses médias — elle
    // se synchronise ensuite vers AnkiWeb et AnkiDroid comme tout média.
    picture: [{
      url: detail.imageUrl,
      filename: `cartometa-${meta.code}-${detail.imageUrl.split('/').pop()}`,
      fields: ['Image'],
    }],
  };
  const carte = rendreMiniCarte(pays.geometries[meta.geom], pays.outline);
  if (carte) {
    note.picture.push({
      data: carte,
      filename: `cartometa-${cle}-map.png`,
      fields: ['RegionMap'],
    });
  }
  return note;
}

// --- Mini-carte --------------------------------------------------------------

const CARTE_LARGEUR = 480;
const CARTE_HAUTEUR = 360;
const CARTE_MARGE = 20;

function anneauxDe(geometrie) {
  if (!geometrie) return [];
  if (geometrie.type === 'Polygon') return [geometrie.coordinates];
  if (geometrie.type === 'MultiPolygon') return geometrie.coordinates;
  return [];
}

// L'emprise de la méta sur la silhouette du pays, en PNG base64 (le format
// de la clé `data` d'AnkiConnect). Projection équirectangulaire corrigée en
// longitude par cos(latitude moyenne) : il s'agit de situer une région d'un
// coup d'œil, pas de naviguer. Sans silhouette (pays hors Natural Earth,
// build hors ligne), l'emprise se cadre toute seule ; sans rien, null — la
// carte Anki se fait alors sans mini-carte plutôt que pas du tout.
function rendreMiniCarte(emprise, contour) {
  const pays = anneauxDe(contour);
  const zone = anneauxDe(emprise);
  const cadre = pays.length ? pays : zone;
  if (!cadre.length) return null;

  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  for (const polygone of cadre) {
    // L'anneau extérieur suffit au cadrage : un trou est toujours dedans.
    for (const [lon, lat] of polygone[0]) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  }

  const latMoyenne = (minLat + maxLat) / 2;
  // Plancher : aux latitudes polaires, cos tend vers 0 et écraserait tout.
  const kx = Math.max(Math.cos((latMoyenne * Math.PI) / 180), 0.05);
  const echelle = Math.min(
    (CARTE_LARGEUR - 2 * CARTE_MARGE) / (((maxLon - minLon) * kx) || 1),
    (CARTE_HAUTEUR - 2 * CARTE_MARGE) / ((maxLat - minLat) || 1),
  );
  const projeter = (lon, lat) => [
    CARTE_LARGEUR / 2 + (lon - (minLon + maxLon) / 2) * kx * echelle,
    CARTE_HAUTEUR / 2 - (lat - latMoyenne) * echelle,
  ];

  const canvas = document.createElement('canvas');
  canvas.width = CARTE_LARGEUR;
  canvas.height = CARTE_HAUTEUR;
  const contexte = canvas.getContext('2d');
  contexte.fillStyle = '#f7f7f2';
  contexte.fillRect(0, 0, CARTE_LARGEUR, CARTE_HAUTEUR);

  const tracer = (polygones) => {
    const chemin = new Path2D();
    for (const polygone of polygones) {
      for (const anneau of polygone) {
        anneau.forEach(([lon, lat], i) => {
          const [x, y] = projeter(lon, lat);
          if (i === 0) chemin.moveTo(x, y);
          else chemin.lineTo(x, y);
        });
        chemin.closePath();
      }
    }
    return chemin;
  };

  if (pays.length) {
    const cheminPays = tracer(pays);
    contexte.fillStyle = '#e4e4dc';
    // evenodd : les trous (enclaves) restent des trous.
    contexte.fill(cheminPays, 'evenodd');
    contexte.strokeStyle = '#9a9a94';
    contexte.lineWidth = 1;
    contexte.stroke(cheminPays);
  }
  if (zone.length) {
    const cheminZone = tracer(zone);
    // Même rouge que le surlignage d'emprise sur la carte (voir app.js et
    // --accent dans style.css), pour un sens identique des deux côtés.
    contexte.fillStyle = 'rgba(193, 40, 58, 0.35)';
    contexte.fill(cheminZone, 'evenodd');
    contexte.strokeStyle = '#c1283a';
    contexte.lineWidth = 2;
    contexte.stroke(cheminZone);
  }
  return canvas.toDataURL('image/png').split(',')[1];
}
```

- [ ] **Étape 2 : test de bout en bout**

Préparation : build complet (`uv run cartometa-build`, avec images), servir sur 8010, Anki ouvert (AnkiConnect configuré comme en tâche 5, étape 3).

Vérifier, dans l'ordre :

1. Méta régionale (ex. un clic en Pologne ou au Botswana) → « Add to Anki » → choisir un paquet → « Add » → le bouton passe à « ✓ Added ».
2. Dans Anki : la note existe dans le paquet choisi, type « Cartometa » ; recto = image de la méta ; verso = mini-carte (emprise rouge sur silhouette grise), explication complète, lien « Plonk It » cliquable ; tags `cartometa` + code pays.
3. Rouvrir la même méta dans le viewer → clic → « Already in Anki », bouton inerte.
4. Méta **nationale** (emprise = pays entier) → la mini-carte montre le pays entier en rouge — attendu, pas un bogue.
5. Fermer Anki → clic sur une autre méta → « Anki isn't responding. » + guide.
6. `Échap` pendant que le panneau paquets est ouvert → la loupe se ferme ; rouvrir une méta → l'état est réinitialisé (bouton frais, panneau caché).
7. Sync Anki → AnkiWeb : l'image et la mini-carte suivent.

- [ ] **Étape 3 : commit**

```bash
git add viewer/anki.js
git commit -m "feat: creation de la carte Anki avec mini-carte d'emprise"
```

---

### Tâche 7 : documentation

**Files:**
- Modify: `README.md`

**Interfaces:** aucune — texte seul.

- [ ] **Étape 1 : section README**

Dans `README.md`, après la section « Fond de carte Google (facultatif) », ajouter :

```markdown
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
```

- [ ] **Étape 2 : relecture d'ensemble et suite de tests**

Run : `uv run python -m pytest`
Attendu : tous PASS.

- [ ] **Étape 3 : commit**

```bash
git add README.md
git commit -m "docs: integration Anki dans le README"
```

---

## Hors périmètre (délibérément)

- Repli `.apkg` pour visiteurs sans AnkiConnect (écarté au cadrage).
- Nom du pays au verso (écarté : les métas sont surtout régionales, la mini-carte le dit mieux).
- Déplacement du port de `cartometa-review` (conflit avec AnkiConnect signalé dans le README, rien de plus).
- Ajout par lot (panier de métas) ; création de paquet depuis le site.
- Tests JS automatisés : le viewer n'a aucune infrastructure de test JS, on n'en introduit pas pour cette fonctionnalité.

## Pièges connus pour l'exécutant

- `uv run pytest` échoue sur cette machine : toujours `uv run python -m pytest`.
- Ne jamais rien construire à partir de `api_key.txt` (ce n'est pas une clé) ; la clé Google vient de `CARTOMETA_GOOGLE_KEY`, déjà réglée — un build sans elle publierait un site sans sélecteur de fond.
- `--skip-images` omet `thumb`/`full` : le bouton Anki est alors invisible par construction. Les tests visuels des tâches 5–6 exigent un build avec images (~30 s grâce au cache).
- L'événement `cartometa:loupe` doit être émis **avant** `loupe.hidden = false` pour que l'état du bloc Anki soit réinitialisé avant d'être visible.
- Les champs d'une note Anki sont du HTML : `description` et `source_url` passent par `echapper()` — ne pas « simplifier » cela.
