const etat = {
  manifeste: null,
  index: [],
  pays: new Map(),   // country code -> {metas, geometries}
  resultats: [],
  categorie: '',
  difficulte: '',
  recherche: '',
  pret: false,   // true only once BOTH manifest and index have loaded successfully
  // These two flags tell `rendre()` (and its callers other than the click: search,
  // category pills) what is actually on screen right now, rather than letting them
  // guess from `resultats` alone.
  chargement: false,   // a request for the current click is in flight
  erreur: false,       // the last click failed; the message stays on screen
};

const carte = L.map('carte', { worldCopyJump: true }).setView([25, 15], 3);
const fondOSM = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 18,
}).addTo(carte);
const surlignage = L.layerGroup().addTo(carte);
// Marks the point actually queried, whether it came from a click or a pasted link:
// the highlight shows a meta's whole footprint, never the point that brought it up.
// Indispensable for a pasted link, which the visitor did not point at on screen;
// useful on click, where the footprint alone does not say which point selected it.
const pointInterroge = L.layerGroup().addTo(carte);
// Blue, and not the site's red accent: that one already highlights a meta's
// footprint on hover, and the marker would blend into what it is supposed to stand
// out from. The same blue as the drawing tool's ground truth
// (`cartometa/review/static/app.js`), for an identical meaning on both sides of the
// project: here is the exact point being talked about.
// Hard-coded for the same reason as the highlight below: Leaflet sets the colour as
// an SVG presentation attribute, where CSS variables are not reliably substituted.
const COULEUR_POINT = '#0057d9';

// Value of the "Not rated" pill. It is not a difficulty the build ever writes — a
// meta nobody has judged simply has no `difficulty` at all — so it needs a marker of
// its own in the template, distinct from the empty value the "All" pill carries.
const NON_EVALUEE = 'none';

// Shortened form shown on the meta card's badge — there is no room for the full word
// next to the country code. Its keys mirror `DIFFICULTIES` in
// `cartometa/build/dataset.py`; a meta with no difficulty gets no badge at all,
// rather than a badge claiming a level nobody has judged.
const ABREVIATIONS_DIFFICULTE = { Beginner: 'Beg.', Intermediate: 'Int.', Pro: 'Pro' };

async function demarrer() {
  try {
    const manifeste = await (await fetch('data/manifest.json')).json();
    etat.manifeste = manifeste;
    etat.index = await (await fetch(`data/${manifeste.index}`)).json();
    document.getElementById('compteurs').textContent =
      `${manifeste.meta_count} metas · ${Object.keys(manifeste.countries).length} countries`;
    etat.pret = true;
    creerSelecteurDeFond();
    restaurerVue();
  } catch (erreur) {
    // Without this net, an unavailable manifest or index leaves a mute page,
    // indistinguishable from a load that is simply still in progress.
    document.getElementById('accueil').textContent =
      'Could not load the meta index. Please reload the page.';
  }
}

// ---------------------------------------------------------------------------
// Base map switch
//
// OpenStreetMap is the default base map, and becomes so again on every page load.
// Nothing from Google is requested — no script, no map instance — until the visitor
// has clicked "Google". This is not an optimisation but the condition of the whole
// arrangement: Google bills on map initialisation, so a passing visitor who stays on
// OSM costs nothing and appears nowhere on Google's side.
//
// The choice is deliberately not remembered: a regular must not find themselves
// calling on Google without having asked for it again.
// ---------------------------------------------------------------------------

let fondGoogle = null;        // built on the first switch, never before
let chargementGoogle = null;  // memoised promise: never two loads

function chargerScript(src) {
  return new Promise((resolve, reject) => {
    const balise = document.createElement('script');
    balise.src = src;
    balise.async = true;
    balise.addEventListener('load', resolve);
    balise.addEventListener('error', () => reject(new Error(`script failed: ${src}`)));
    document.head.append(balise);
  });
}

async function preparerFondGoogle() {
  // `loading=async` is the form Google has required since 2023, and it mandates a
  // `callback`. We do not use it: what we wait for is the tag's `load` event,
  // `Function.prototype` is only there to satisfy the mandatory parameter.
  await chargerScript(
    'https://maps.googleapis.com/maps/api/js'
    + `?key=${encodeURIComponent(etat.manifeste.google_key)}`
    + '&loading=async&callback=Function.prototype'
  );
  // The plugin only needs Leaflet to register itself, but loading it afterwards
  // keeps the two possible failures in the order one diagnoses them.
  await chargerScript(etat.manifeste.google_mutant);
  return L.gridLayer.googleMutant({ type: 'roadmap' });
}

function creerSelecteurDeFond() {
  // Without a key, no switch at all: a contributor who builds the site locally gets
  // a whole preview, simply missing the second base map.
  if (!etat.manifeste.google_key || !etat.manifeste.google_mutant) return;

  const controle = L.control({ position: 'topright' });
  controle.onAdd = () => {
    const boite = L.DomUtil.create('div', 'choix-fond');
    // Without this, clicking the switch would also fire `carte.on('click')`: the
    // visitor would change base map AND query the point under the button.
    L.DomEvent.disableClickPropagation(boite);

    const boutons = {};
    const marquer = (actif) => {
      for (const [nom, bouton] of Object.entries(boutons)) {
        bouton.classList.toggle('actif', nom === actif);
        bouton.setAttribute('aria-pressed', String(nom === actif));
      }
    };

    // Fallback shared by the two ways Google can let us down. The second was
    // observed in production: a refused key does not make the script's promise
    // fail — it loads perfectly well, then the API calls `window.gm_authFailure` and
    // simply draws nothing. Without this hook-up, the visitor is left facing a grey
    // rectangle, OSM having already been removed, and the button keeps showing lit.
    function abandonnerGoogle() {
      chargementGoogle = null;
      boutons.google.textContent = 'Google';
      boutons.google.disabled = true;
      boutons.google.title = 'Google basemap unavailable';
      basculer('osm');
    }
    // Name imposed by the Google API, which calls it on the global object: invalid
    // key, no billing, exhausted quota.
    window.gm_authFailure = abandonnerGoogle;

    async function basculer(vers) {
      if (vers === 'osm') {
        if (fondGoogle) carte.removeLayer(fondGoogle);
        fondOSM.addTo(carte);
        marquer('osm');
        return;
      }
      marquer('google');
      if (!fondGoogle) {
        boutons.google.textContent = '…';
        try {
          // Memoised: two impatient clicks do not load twice.
          chargementGoogle = chargementGoogle || preparerFondGoogle();
          fondGoogle = await chargementGoogle;
        } catch (erreur) {
          // Script unreachable or blocked (network, content blocker): without this
          // fallback, the map would stay blank with nothing to explain it. A refused
          // key, on the other hand, does not come through here — see
          // `abandonnerGoogle`.
          abandonnerGoogle();
          return;
        }
        boutons.google.textContent = 'Google';
      }
      carte.removeLayer(fondOSM);
      fondGoogle.addTo(carte);
    }

    for (const [nom, libelle] of [['osm', 'OSM'], ['google', 'Google']]) {
      const bouton = L.DomUtil.create('button', '', boite);
      bouton.type = 'button';
      bouton.textContent = libelle;
      bouton.addEventListener('click', () => basculer(nom));
      boutons[nom] = bouton;
    }
    marquer('osm');
    return boite;
  };
  controle.addTo(carte);
}

// A country is downloaded only once, and the promise is memoised: two quick clicks
// in the same country do not trigger two requests.
const enCours = new Map();
function chargerPays(code) {
  if (etat.pays.has(code)) return Promise.resolve(etat.pays.get(code));
  if (enCours.has(code)) return enCours.get(code);
  const entree = etat.manifeste.countries[code];
  const promesse = fetch(`data/${entree.file}`)
    .then((r) => r.json())
    .then((contenu) => {
      etat.pays.set(code, contenu);
      return contenu;
    })
    // If the fetch fails, remove the entry in every case: otherwise a mere network
    // outage would lock that country behind a rejected promise forever, and no later
    // click could retry the load.
    .finally(() => enCours.delete(code));
  enCours.set(code, promesse);
  return promesse;
}

function dansAnneau(lon, lat, anneau) {
  let dedans = false;
  for (let i = 0, j = anneau.length - 1; i < anneau.length; j = i++) {
    const [xi, yi] = anneau[i];
    const [xj, yj] = anneau[j];
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      dedans = !dedans;
    }
  }
  return dedans;
}

function dansPolygone(lon, lat, anneaux) {
  if (!dansAnneau(lon, lat, anneaux[0])) return false;
  for (let i = 1; i < anneaux.length; i += 1) {
    if (dansAnneau(lon, lat, anneaux[i])) return false; // hole
  }
  return true;
}

function contient(geometrie, lon, lat) {
  if (geometrie.type === 'Polygon') return dansPolygone(lon, lat, geometrie.coordinates);
  return geometrie.coordinates.some((anneaux) => dansPolygone(lon, lat, anneaux));
}

async function interroger(lon, lat, surPartiel) {
  // The index is already sorted by increasing area: the result order is from most
  // specific to most general, with no re-sorting. A footprint with far-apart parts
  // (Russia across ±180°) takes up several rows — same id, distinct bbox — hence the
  // deduplication: the first row whose bbox contains the point is enough, the precise
  // test is done on the whole geometry.
  const vus = new Set();
  const candidats = [];
  for (const ligne of etat.index) {
    const [id, , minLon, minLat, maxLon, maxLat] = ligne;
    if (lon < minLon || lon > maxLon || lat < minLat || lat > maxLat) continue;
    if (vus.has(id)) continue;
    vus.add(id);
    candidats.push(ligne);
  }
  const codes = [...new Set(candidats.map(([, code]) => code))];

  // The point-in-polygon test is memoised per geometry: since geometries are
  // deduplicated on the build side, the 19 Russian national metas share the same
  // outline — testing it once is enough.
  const cacheContient = new Map();
  const charges = new Set();
  const resultatsCharges = () => candidats
    .filter(([id, code]) => {
      if (!charges.has(code)) return false;
      const pays = etat.pays.get(code);
      const empreinte = pays.metas[id].geom;
      const cle = `${code}/${empreinte}`;
      if (!cacheContient.has(cle)) {
        cacheContient.set(cle, contient(pays.geometries[empreinte], lon, lat));
      }
      return cacheContient.get(cle);
    })
    .map(([id, code]) => ({ id, code, ...etat.pays.get(code).metas[id] }));

  // Incremental rendering: each country shows up as soon as it arrives, instead of
  // waiting for the slowest. `resultatsCharges` recomputes the full list in index
  // order, so the ordering by area stays correct whatever order the files arrive in.
  await Promise.all(codes.map((code) => chargerPays(code).then(() => {
    charges.add(code);
    if (surPartiel && charges.size < codes.length) surPartiel(resultatsCharges());
  })));
  return resultatsCharges();
}

// Generation counter: incremented on every click, so that a slower click does not
// overwrite the display of a more recent click that has already resolved.
let generation = 0;

// The single path of every query, whether it comes from a click on the map or from a
// pasted link: one place carries the generation counter, the state flags and the error
// handling. Two copies of this logic would end up drifting apart.
async function allerAuPoint(lon, lat) {
  const generationDuClic = ++generation;
  document.getElementById('accueil').hidden = true;
  document.getElementById('filtres').hidden = false;
  etat.chargement = true;
  etat.erreur = false;
  afficherSquelettes();
  surlignage.clearLayers();
  pointInterroge.clearLayers();
  // Placed before the network call: the marker appears on click, without waiting for
  // the gallery. It also survives a load failure, where it remains the only trace of
  // what was asked for.
  L.circleMarker([lat, lon], {
    // interactive: false for the same reason as the highlight — an interactive layer
    // captures the click and makes the map mute under the marker.
    interactive: false,
    radius: 6, color: COULEUR_POINT, weight: 2,
    fillColor: COULEUR_POINT, fillOpacity: 0.35,
  }).addTo(pointInterroge);
  let resultats;
  try {
    resultats = await interroger(lon, lat, (partiels) => {
      // A more recent click has taken over: its skeletons and its own results must
      // not be overwritten by this leftover.
      if (generationDuClic !== generation) return;
      // As long as nothing is found, we keep the skeletons: showing "no meta" while
      // countries are still loading would be lying.
      if (!partiels.length) return;
      etat.resultats = partiels;
      rendre();
    });
  } catch (erreur) {
    // Without this net, a country that fails to load leaves the gallery stuck on the
    // skeletons, with no way for the visitor to know something failed.
    if (generationDuClic !== generation) return; // a more recent click took over
    // Emptying `resultats` is essential, not cosmetic: without it, a filter typed
    // right after this failure would apply to the previous click's results (or to the
    // initial array) and would show either "no meta" for a mere network problem or,
    // worse, real cards from another point as if they belonged to this one.
    etat.resultats = [];
    etat.chargement = false;
    etat.erreur = true;
    montrer({ message: 'Could not load metas for this area.' });
    return;
  }
  // This click is no longer the most recent: its result is stale, we ignore it.
  if (generationDuClic !== generation) return;
  etat.resultats = resultats;
  etat.chargement = false;
  etat.erreur = false;
  rendre();
  memoriserVue();
}

carte.on('click', (evenement) => {
  // Without this safety rail, a first click after a startup failure immediately wipes
  // the error message in #accueil and renders an empty gallery without an exception:
  // the visitor loses the only explanation they will ever have had.
  if (!etat.pret) return;
  // `.wrap()`: with `worldCopyJump`, a click on a repeated copy of the world
  // (zoom ≤ 2) carries a longitude outside ±180°, which nothing in `etat.index`
  // (bboxes within ±180°) can ever cover — a perfectly valid click would come back
  // as "no meta" for no visible reason.
  const { lng: lon, lat } = evenement.latlng.wrap();
  allerAuPoint(lon, lat);
});

function memoriserVue() {
  const centre = carte.getCenter();
  history.replaceState(null, '',
    `#${centre.lat.toFixed(4)},${centre.lng.toFixed(4)},${carte.getZoom()}`);
}

function restaurerVue() {
  const [lat, lon, zoom] = location.hash.slice(1).split(',').map(Number);
  if ([lat, lon, zoom].every(Number.isFinite)) carte.setView([lat, lon], zoom);
}

carte.on('moveend', memoriserVue);
demarrer();

const loupe = document.getElementById('loupe');

// The scope sections come from the template: the script only fills their grid and
// hides them, never recreates them. That is what lets the expanded/collapsed state
// chosen by the visitor survive every render — a <details> rebuilt on every keystroke
// in the search box would reopen under their fingers. The DOM order (regional then
// national) carries the display order: nothing in the script has to restate it.
const groupes = [...document.querySelectorAll('.groupe')].map((element) => ({
  element,
  portee: element.dataset.portee,
  grille: element.querySelector('.grille'),
  compte: element.querySelector('.compte'),
}));
const squelettes = document.getElementById('squelettes');
const messageVide = document.getElementById('vide');

function urlImage(nom) {
  return etat.manifeste.image_base + nom;
}

// The gallery's three states are exclusive — waiting skeletons, a lone message, or
// filled sections — and each has to switch the other two off. Going through a single
// point stops a path from forgetting to switch one off and leaving, for instance, an
// error message above the previous click's cards.
function montrer({ chargement = false, message = '' } = {}) {
  squelettes.hidden = !chargement;
  messageVide.hidden = !message;
  if (message) messageVide.textContent = message;
  if (chargement || message) {
    for (const groupe of groupes) groupe.element.hidden = true;
  }
}

function afficherSquelettes() {
  squelettes.innerHTML = '<div class="squelette"></div>'.repeat(4);
  montrer({ chargement: true });
}

function visibles() {
  const terme = etat.recherche.trim().toLowerCase();
  return etat.resultats.filter((meta) => {
    if (etat.categorie && meta.category !== etat.categorie) return false;
    // Strict match, like the category filter: "Intermediate" shows the Intermediate
    // metas and nothing else. `NON_EVALUEE` is the one choice that matches on
    // absence — the metas still waiting to be judged.
    if (etat.difficulte === NON_EVALUEE) {
      if (meta.difficulty) return false;
    } else if (etat.difficulte && meta.difficulty !== etat.difficulte) return false;
    if (!terme) return true;
    return `${meta.title} ${meta.description}`.toLowerCase().includes(terme);
  });
}

function creerCarte(meta) {
  const bloc = document.createElement('article');
  bloc.className = 'carte-meta';
  // textContent rather than innerHTML: the titles come from third-party HTML and can
  // contain anything.
  // A meta with no image (the build omits `thumb`/`full` together when there is no
  // source) keeps its place in the gallery: only the thumbnail is omitted, not the
  // card, so that the count shown always matches the number of metas found.
  if (meta.thumb) {
    const image = document.createElement('img');
    image.loading = 'lazy';
    image.src = urlImage(meta.thumb);
    image.alt = '';
    bloc.appendChild(image);
  }
  const legende = document.createElement('p');
  const code = document.createElement('span');
  code.className = 'code-pays';
  code.textContent = meta.code;
  legende.append(code, document.createTextNode(meta.title));
  bloc.appendChild(legende);
  // Below the title: difficulty (abbreviated, grey), appearing after country + title.
  // Absent on a meta nobody has judged: the card then says nothing about its level,
  // which is exactly what is known about it.
  if (meta.difficulty) {
    const difficulte = document.createElement('span');
    difficulte.className = 'badge-difficulte';
    difficulte.textContent = ABREVIATIONS_DIFFICULTE[meta.difficulty];
    bloc.appendChild(difficulte);
  }
  bloc.addEventListener('mouseenter', () => {
    surlignage.clearLayers();
    // Hard-coded colour and not `var(--accent)`: Leaflet sets it as an SVG
    // presentation attribute, where CSS variable substitution is not reliable across
    // browsers. Keep both values in sync with `--accent` in style.css.
    L.geoJSON(etat.pays.get(meta.code).geometries[meta.geom], {
      // interactive: false — otherwise the highlight layer captures the click in its
      // place (Leaflet calls `DomEvent.fakeStop`, which stops `carte.on('click')` from
      // firing): the whole area would stay mute on the first click until the mouse has
      // left it.
      interactive: false,
      color: '#c1283a', weight: 2, fillOpacity: 0.18,
    }).addTo(surlignage);
  });
  bloc.addEventListener('click', () => ouvrirLoupe(meta));
  return bloc;
}

function rendre() {
  const metas = visibles();
  if (!metas.length) {
    montrer({ message: etat.resultats.length
      ? 'No meta matches this filter.'
      : 'No meta covers this point.' });
    return;
  }
  montrer();
  for (const groupe of groupes) {
    const siennes = metas.filter((meta) => meta.scope === groupe.portee);
    groupe.grille.replaceChildren(...siennes.map(creerCarte));
    groupe.compte.textContent = siennes.length;
    // A section with no result is removed rather than shown at zero: the clicked
    // point is simply covered by one scope only, that is not a gap worth reporting.
    // The count of the one that remains already says everything.
    groupe.element.hidden = !siennes.length;
  }
}

function ouvrirLoupe(meta) {
  const image = document.getElementById('loupe-image');
  // Same shortcoming as for the thumbnail: without `full`, do not request
  // "img/undefined" nor open an empty blow-up. The image is hidden, but the title and
  // the source link stay on screen.
  image.hidden = !meta.full;
  image.src = meta.full ? urlImage(meta.full) : '';
  const texte = document.getElementById('loupe-texte');
  // A hand-entered meta does not necessarily have a source: the field is optional on
  // entry, because such metas are often found while exploring a map and have no
  // original page to cite. Without a guard, we would show a "source" link that leads
  // nowhere.
  if (meta.source_url) {
    texte.textContent = `${meta.title} `;
    const lien = document.createElement('a');
    lien.href = meta.source_url;
    lien.target = '_blank';
    lien.rel = 'noopener';
    lien.textContent = 'source';
    texte.appendChild(lien);
  } else {
    texte.textContent = meta.title;
  }
  const description = document.getElementById('loupe-description');
  // textContent for the same reason as the cards: descriptions come from third-party
  // HTML and can contain anything. Two out of three descriptions open with the title
  // verbatim (the title is extracted from the description's opening): showing both
  // would print the same sentence twice in a row, so the title prefix is stripped —
  // but only when the title is a complete sentence. A fragment title ("Yellow",
  // "Pas de la Casa") continues its sentence in the description, and the remainder
  // alone would start mid-sentence; there the whole description is kept. A description
  // that says nothing beyond the title — or none at all, the field is optional on
  // hand-entered metas — hides the paragraph entirely rather than leaving an empty
  // block between the title and the Anki zone.
  const complet = (meta.description || '').trim();
  const titre = (meta.title || '').trim();
  let reste = complet;
  if (complet === titre) {
    reste = '';
  } else if (/[.!?…:]$/.test(titre) && complet.startsWith(titre)) {
    reste = complet.slice(titre.length).trim();
  }
  description.textContent = reste;
  description.hidden = !reste;
  // Everything the Anki module needs to know goes through this event: app.js does not
  // know about Anki, anki.js knows neither the map nor the gallery. The image URL is
  // absolute because it leaves the page — it is Anki (the software) that will download
  // it, not this browser.
  document.dispatchEvent(new CustomEvent('cartometa:loupe', {
    detail: {
      meta,
      pays: etat.pays.get(meta.code),
      imageUrl: meta.full ? new URL(urlImage(meta.full), location.href).href : null,
    },
  }));
  loupe.hidden = false;
}

function fermerLoupe() {
  loupe.hidden = true;
  document.getElementById('loupe-image').src = '';
  document.dispatchEvent(new Event('cartometa:loupe-fermee'));
}

document.getElementById('loupe-fermer').addEventListener('click', fermerLoupe);
loupe.addEventListener('click', (e) => { if (e.target === loupe) fermerLoupe(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') fermerLoupe(); });

document.getElementById('recherche').addEventListener('input', (e) => {
  // During a load or after an error, `resultats` corresponds to nothing displayable
  // for the current click (empty, or stale from a previous click): filtering on it
  // would replace the skeleton or the error message with a misleading render. We
  // ignore the interaction; the click in progress (or the next one) will render the
  // up-to-date state itself.
  if (etat.chargement || etat.erreur) return;
  etat.recherche = e.target.value;
  rendre();
});

// Category and difficulty filters: two groups, one behaviour — a single active
// choice per group, whose empty value ("All") filters nothing. Both are combined
// with the search in `visibles`. Scope is no longer a filter: it splits the results
// between the two collapsible sections, which are therefore read together.
//
// Each group is queried inside its own container, and not through a bare `.pastille`
// selector: a click in one group must never touch the other's `active` state. One
// function rather than two identical loops, so the two cannot drift apart.
function brancherFiltre(conteneur, champ) {
  const pastilles = [...document.querySelectorAll(`#${conteneur} .pastille`)];
  for (const bouton of pastilles) {
    bouton.addEventListener('click', () => {
      // Same safety rail as for the search: see the comment above.
      if (etat.chargement || etat.erreur) return;
      for (const autre of pastilles) autre.classList.toggle('active', autre === bouton);
      etat[champ] = bouton.dataset[champ];
      rendre();
    });
  }
}
brancherFiltre('filtres-categorie', 'categorie');
brancherFiltre('filtres-difficulte', 'difficulte');

// --- Street View link bar --------------------------------------------------

// Close enough to recognise the place, wide enough to place the city around it: a
// Street View link designates a point, not a footprint.
const ZOOM_LIEN = 14;

// Hosts of the shortened links, aligned with `MAPS_RE` in
// cartometa/extract/maps_links.py.
const LIEN_COURT = /^https?:\/\/(?:maps\.app\.goo\.gl|goo\.gl)\//i;

// Forms that carry coordinates, from the most reliable to the most incidental. The
// first two are the ones actually observed across the 2007 Plonk It links resolved by
// the build (cf. `LATLON_RE` and `VIEWPOINT_RE`); the rest cover the other ways Google
// Maps writes a point into a URL.
const MOTIFS_LATLON = [
  /\/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,             // /@LAT,LON — Street View camera
  /[?&]viewpoint=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,  // api=1 panorama viewer
  /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/,           // place card
  /[?&]cbll=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,       // legacy Street View
  /[?&](?:q|query|ll|center)=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,
];

function validerLatLon(lat, lon) {
  const a = Number(lat);
  const b = Number(lon);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  // A pattern can match something other than a point — `!3d` serves several purposes
  // inside a `data=` blob. Out of bounds, we refuse rather than send the map nowhere.
  if (a < -90 || a > 90 || b < -180 || b > 180) return null;
  return [a, b];
}

function coordsDepuisUrl(texte) {
  for (const motif of MOTIFS_LATLON) {
    const trouve = texte.match(motif);
    if (trouve) {
      const point = validerLatLon(trouve[1], trouve[2]);
      if (point) return point;
    }
  }
  return null;
}

const champLien = document.getElementById('lien');
const messageLien = document.getElementById('lien-etat');

function direLien(message, echec = false) {
  messageLien.textContent = message;
  messageLien.classList.toggle('echec', echec);
}

async function resoudreLienCourt(url) {
  // A short link is unreadable from the browser: goo.gl sends no CORS header
  // (verified), so the redirect cannot be followed here. `/api/resolve` follows it
  // server-side and returns nothing but the point.
  // `v=2` is part of the browser's cache key, and that is its entire purpose. The
  // first version returned its failures with `max-age=86400`: a visitor who hit a
  // missed resolution keeps that negative answer cached for 24 h, and fixing the
  // server changes nothing since their browser never calls it again. Changing the
  // address creates a new entry and gets them out of it without asking anything of
  // them. To be incremented if such an episode happens again.
  const reponse = await fetch(`/api/resolve?v=2&url=${encodeURIComponent(url)}`);
  // Throwing rather than returning `null`: an unreachable relay and a link without
  // coordinates call for two different messages. Conflating them really did cost a
  // diagnosis — "no coordinates" blamed the link while the fault was elsewhere.
  if (!reponse.ok) throw new Error(`resolve ${reponse.status}`);
  const charge = await reponse.json();
  return Array.isArray(charge.latlon)
    ? validerLatLon(charge.latlon[0], charge.latlon[1])
    : null;
}

// Same reason as `generation` for clicks: resolving a short link goes over the
// network, so a first paste can complete after a second one. Without this counter, the
// slowest link would move the map last.
let generationLien = 0;

// A link copied from an address bar sometimes arrives without its scheme. Rejecting it
// for that would be gratuitous: we complete it when what follows looks like a host, and
// let `LIEN_COURT` and `new URL` judge afterwards.
function normaliser(saisie) {
  return /^[a-z]+:\/\//i.test(saisie) ? saisie : `https://${saisie}`;
}

async function suivreLien(saisie) {
  const propre = saisie.trim();
  if (!propre) return;
  const brut = normaliser(propre);
  if (!etat.pret) {
    direLien('Index not loaded yet.', true);
    return;
  }
  const monTour = ++generationLien;
  let point = coordsDepuisUrl(brut);
  if (!point && LIEN_COURT.test(brut)) {
    direLien('Resolving…');
    try {
      point = await resoudreLienCourt(brut);
    } catch (erreur) {
      if (monTour !== generationLien) return;
      direLien("Couldn't resolve that short link. Try again.", true);
      return;
    }
    if (monTour !== generationLien) return; // a more recent link took over
  }
  if (!point) {
    direLien('No coordinates found in that link.', true);
    return;
  }
  direLien('');
  const [lat, lon] = point;
  carte.setView([lat, lon], ZOOM_LIEN);
  allerAuPoint(lon, lat);
}

document.getElementById('barre-lien').addEventListener('submit', (evenement) => {
  evenement.preventDefault();
  suivreLien(champLien.value);
});

// Pasting is enough to set off: that is the expected gesture, and both the button and
// the Enter key stay available. We write the value ourselves after `preventDefault` so
// as not to depend on the ordering between the paste event and the browser's update of
// the field.
champLien.addEventListener('paste', (evenement) => {
  const colle = evenement.clipboardData?.getData('text') ?? '';
  if (!colle.trim()) return;
  evenement.preventDefault();
  champLien.value = colle.trim();
  suivreLien(champLien.value);
});
