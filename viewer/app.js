const etat = {
  manifeste: null,
  index: [],
  pays: new Map(),   // code pays -> {metas, geometries}
  resultats: [],
  categorie: '',
  portee: '',        // '' | 'regional' | 'national', voir scope_de côté build
  recherche: '',
  pret: false,   // true seulement une fois manifeste ET index chargés avec succès
  // Ces deux drapeaux disent à `rendre()` (et à ses appelants autres que le
  // clic : recherche, pastilles) ce qu'il y a réellement à l'écran en ce
  // moment, plutôt que de les laisser deviner d'après `resultats` seul.
  chargement: false,   // une requête pour le clic courant est en vol
  erreur: false,       // le dernier clic a échoué ; le message reste affiché
};

const carte = L.map('carte', { worldCopyJump: true }).setView([25, 15], 3);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 18,
}).addTo(carte);
const surlignage = L.layerGroup().addTo(carte);
// Marque le point réellement interrogé, qu'il vienne d'un clic ou d'un lien
// collé : le surlignage montre l'emprise entière d'une méta, jamais le point
// qui l'a fait apparaître. Indispensable pour un lien collé, que le visiteur
// n'a pas désigné à l'écran ; utile au clic, où l'emprise seule ne dit pas
// quel point l'a sélectionnée.
const pointInterroge = L.layerGroup().addTo(carte);
// Bleu, et non l'accent rouge du site : celui-ci sert déjà à surligner
// l'emprise d'une méta au survol, et le repère se confondrait avec ce qu'il
// est censé distinguer. Même bleu que la vérité terrain de l'outil de tracé
// (`cartometa/review/static/app.js`), pour un sens identique des deux côtés
// du projet : voici le point exact dont on parle.
// En dur pour la même raison que le surlignage ci-dessous : Leaflet pose la
// couleur en attribut de présentation SVG, où les variables CSS ne sont pas
// substituées de façon fiable.
const COULEUR_POINT = '#0057d9';

async function demarrer() {
  try {
    const manifeste = await (await fetch('data/manifest.json')).json();
    etat.manifeste = manifeste;
    etat.index = await (await fetch(`data/${manifeste.index}`)).json();
    document.getElementById('compteurs').textContent =
      `${manifeste.meta_count} metas · ${Object.keys(manifeste.countries).length} countries`;
    etat.pret = true;
    restaurerVue();
  } catch (erreur) {
    // Sans ce filet, un manifeste ou un index indisponible laisse une page
    // muette, indiscernable d'un simple chargement encore en cours.
    document.getElementById('accueil').textContent =
      'Could not load the meta index. Please reload the page.';
  }
}

// Un pays n'est téléchargé qu'une fois, et la promesse est mémorisée : deux
// clics rapides dans le même pays ne déclenchent pas deux requêtes.
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
    // Si le fetch échoue, retirer l'entrée dans tous les cas : sinon une simple
    // coupure réseau bloquerait ce pays derrière une promesse rejetée pour
    // toujours, et aucun clic ultérieur ne pourrait retenter le chargement.
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
    if (dansAnneau(lon, lat, anneaux[i])) return false; // trou
  }
  return true;
}

function contient(geometrie, lon, lat) {
  if (geometrie.type === 'Polygon') return dansPolygone(lon, lat, geometrie.coordinates);
  return geometrie.coordinates.some((anneaux) => dansPolygone(lon, lat, anneaux));
}

async function interroger(lon, lat) {
  // L'index est déjà trié par surface croissante : l'ordre du résultat est
  // celui du plus spécifique au plus général, sans retrier.
  const candidats = etat.index.filter(([, , minLon, minLat, maxLon, maxLat]) =>
    lon >= minLon && lon <= maxLon && lat >= minLat && lat <= maxLat);
  const codes = [...new Set(candidats.map(([, code]) => code))];
  await Promise.all(codes.map(chargerPays));
  return candidats
    .filter(([id, code]) => contient(etat.pays.get(code).geometries[id], lon, lat))
    .map(([id, code]) => ({ id, code, ...etat.pays.get(code).metas[id] }));
}

// Compteur de génération : incrémenté à chaque clic, pour qu'un clic plus
// lent ne vienne pas écraser l'affichage d'un clic plus récent déjà résolu.
let generation = 0;

// Chemin unique de toute interrogation, qu'elle vienne d'un clic sur la carte
// ou d'un lien collé : un seul endroit porte le compteur de génération, les
// drapeaux d'état et le traitement d'erreur. Deux copies de cette logique
// finiraient par divertir l'une de l'autre.
async function allerAuPoint(lon, lat) {
  const generationDuClic = ++generation;
  document.getElementById('accueil').hidden = true;
  document.getElementById('filtres').hidden = false;
  etat.chargement = true;
  etat.erreur = false;
  afficherSquelettes();
  surlignage.clearLayers();
  pointInterroge.clearLayers();
  // Posé avant l'appel réseau : le repère apparaît au clic, sans attendre la
  // galerie. Il survit aussi à un échec de chargement, où il reste la seule
  // trace de ce qui a été demandé.
  L.circleMarker([lat, lon], {
    // interactive: false pour la même raison que le surlignage — un calque
    // interactif capte le clic et rend la carte muette sous le marqueur.
    interactive: false,
    radius: 6, color: COULEUR_POINT, weight: 2,
    fillColor: COULEUR_POINT, fillOpacity: 0.35,
  }).addTo(pointInterroge);
  let resultats;
  try {
    resultats = await interroger(lon, lat);
  } catch (erreur) {
    // Sans ce filet, un pays qui échoue à charger laisse la galerie bloquée
    // sur les squelettes, sans que le visiteur sache que quelque chose a échoué.
    if (generationDuClic !== generation) return; // un clic plus récent a pris le relais
    // Vider `resultats` est essentiel, pas cosmétique : sans ça, un filtre
    // tapé juste après cet échec s'appliquerait aux résultats du clic
    // précédent (ou au tableau initial) et afficherait soit « aucun meta »
    // pour un simple problème réseau, soit pire, de vraies cartes d'un autre
    // point comme si elles appartenaient à celui-ci.
    etat.resultats = [];
    etat.chargement = false;
    etat.erreur = true;
    document.getElementById('galerie').innerHTML =
      '<p id="vide">Could not load metas for this area.</p>';
    return;
  }
  // Ce clic n'est plus le plus récent : son résultat est périmé, on l'ignore.
  if (generationDuClic !== generation) return;
  etat.resultats = resultats;
  etat.chargement = false;
  etat.erreur = false;
  rendre();
  memoriserVue();
}

carte.on('click', (evenement) => {
  // Sans ce garde-fou, un premier clic après un échec au démarrage efface
  // aussitôt le message d'erreur dans #accueil et rend une galerie vide sans
  // exception : le visiteur perd la seule explication qu'il aura jamais eue.
  if (!etat.pret) return;
  // `.wrap()` : avec `worldCopyJump`, un clic sur une copie répétée du monde
  // (zoom ≤ 2) porte une longitude hors ±180°, que rien dans `etat.index`
  // (des bbox en ±180°) ne peut jamais recouvrir — un clic pourtant valide
  // ressortirait « aucune méta » sans raison visible.
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

const galerie = document.getElementById('galerie');
const loupe = document.getElementById('loupe');

function urlImage(nom) {
  return etat.manifeste.image_base + nom;
}

function afficherSquelettes() {
  galerie.innerHTML = '<div class="squelette"></div>'.repeat(4);
}

function visibles() {
  const terme = etat.recherche.trim().toLowerCase();
  return etat.resultats.filter((meta) => {
    if (etat.categorie && meta.category !== etat.categorie) return false;
    if (etat.portee && meta.scope !== etat.portee) return false;
    if (!terme) return true;
    return `${meta.title} ${meta.description}`.toLowerCase().includes(terme);
  });
}

function rendre() {
  const metas = visibles();
  galerie.innerHTML = '';
  if (!metas.length) {
    const vide = document.createElement('p');
    vide.id = 'vide';
    vide.textContent = etat.resultats.length
      ? 'No meta matches this filter.'
      : 'No meta covers this point.';
    galerie.appendChild(vide);
    return;
  }
  for (const meta of metas) {
    const bloc = document.createElement('article');
    bloc.className = 'carte-meta';
    // textContent plutôt qu'innerHTML : les titres viennent d'un HTML tiers
    // et peuvent contenir n'importe quoi.
    // Une meta sans image (le build omet `thumb`/`full` ensemble quand il
    // n'y a pas de source) garde sa place dans la galerie : seule la
    // vignette est omise, pas la carte, pour que le compte affiché
    // corresponde toujours au nombre de metas trouvées.
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
    bloc.addEventListener('mouseenter', () => {
      surlignage.clearLayers();
      // Couleur en dur et non `var(--accent)` : Leaflet la pose comme attribut
      // de présentation SVG, où la substitution des variables CSS n'est pas
      // fiable selon les navigateurs. Garder les deux valeurs synchronisées
      // avec `--accent` dans style.css.
      L.geoJSON(etat.pays.get(meta.code).geometries[meta.id], {
        // interactive: false — sinon le calque du surlignage capte le clic
        // à sa place (Leaflet appelle `DomEvent.fakeStop`, qui empêche
        // `carte.on('click')` de se déclencher) : la zone entière resterait
        // muette au premier clic tant que la souris ne l'a pas quittée.
        interactive: false,
        color: '#c1283a', weight: 2, fillOpacity: 0.18,
      }).addTo(surlignage);
    });
    bloc.addEventListener('click', () => ouvrirLoupe(meta));
    galerie.appendChild(bloc);
  }
}

function ouvrirLoupe(meta) {
  const image = document.getElementById('loupe-image');
  // Même défaut que pour la vignette : sans `full`, ne pas demander
  // « img/undefined » ni ouvrir un agrandissement vide. L'image est
  // masquée, mais le titre et le lien source restent affichés.
  image.hidden = !meta.full;
  image.src = meta.full ? urlImage(meta.full) : '';
  const texte = document.getElementById('loupe-texte');
  // Une méta saisie à la main n'a pas forcément de source : le champ est
  // facultatif à la saisie, parce que ces métas sont souvent trouvées en
  // explorant une carte et n'ont aucune page d'origine à citer. Sans garde,
  // on afficherait un lien « source » qui ne mène nulle part.
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
  loupe.hidden = false;
}

function fermerLoupe() {
  loupe.hidden = true;
  document.getElementById('loupe-image').src = '';
}

document.getElementById('loupe-fermer').addEventListener('click', fermerLoupe);
loupe.addEventListener('click', (e) => { if (e.target === loupe) fermerLoupe(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') fermerLoupe(); });

document.getElementById('recherche').addEventListener('input', (e) => {
  // Pendant un chargement ou après une erreur, `resultats` ne correspond à
  // rien d'affichable pour le clic courant (vide, ou périmé d'un clic
  // précédent) : filtrer dessus remplacerait le squelette ou le message
  // d'erreur par un rendu trompeur. On ignore l'interaction ; le clic en
  // cours (ou le prochain) rendra lui-même l'état à jour.
  if (etat.chargement || etat.erreur) return;
  etat.recherche = e.target.value;
  rendre();
});

// Les deux filtres se comportent à l'identique : un seul choix actif par
// groupe, et ils se cumulent entre eux (et avec la recherche) dans `visibles`.
function brancherGroupe(selecteur, champDonnee, cle) {
  for (const bouton of document.querySelectorAll(selecteur)) {
    bouton.addEventListener('click', () => {
      // Même garde-fou que pour la recherche : voir le commentaire ci-dessus.
      if (etat.chargement || etat.erreur) return;
      for (const autre of document.querySelectorAll(selecteur)) {
        autre.classList.toggle('active', autre === bouton);
      }
      etat[cle] = bouton.dataset[champDonnee];
      rendre();
    });
  }
}

brancherGroupe('.pastille', 'categorie', 'categorie');
brancherGroupe('.segment', 'portee', 'portee');

// --- Barre de lien Street View ---------------------------------------------

// Assez près pour reconnaître l'endroit, assez large pour situer la ville
// autour : un lien Street View désigne un point, pas une emprise.
const ZOOM_LIEN = 14;

// Hôtes des liens raccourcis, alignés sur `MAPS_RE` de
// cartometa/extract/maps_links.py.
const LIEN_COURT = /^https?:\/\/(?:maps\.app\.goo\.gl|goo\.gl)\//i;

// Formes porteuses de coordonnées, de la plus fiable à la plus incidente. Les
// deux premières sont celles réellement observées sur les 2007 liens Plonk It
// résolus par le build (cf. `LATLON_RE` et `VIEWPOINT_RE`) ; les suivantes
// couvrent les autres façons dont Google Maps inscrit un point dans une URL.
const MOTIFS_LATLON = [
  /\/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,             // /@LAT,LON — caméra Street View
  /[?&]viewpoint=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,  // viewer panorama api=1
  /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/,           // fiche de lieu
  /[?&]cbll=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,       // ancien Street View
  /[?&](?:q|query|ll|center)=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,
];

function validerLatLon(lat, lon) {
  const a = Number(lat);
  const b = Number(lon);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  // Un motif peut coïncider avec autre chose qu'un point — `!3d` sert à
  // plusieurs usages dans un blob `data=`. Hors bornes, on refuse plutôt que
  // d'envoyer la carte nulle part.
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
  // Un lien court est illisible depuis le navigateur : goo.gl n'envoie aucun
  // en-tête CORS (vérifié), donc la redirection ne peut pas être suivie ici.
  // `/api/resolve` la suit côté serveur et ne renvoie que le point.
  // `v=2` fait partie de la clé de cache du navigateur, et c'est tout son
  // objet. La première version renvoyait ses échecs avec `max-age=86400` :
  // un visiteur ayant essuyé une résolution manquée garde cette réponse
  // négative en cache pendant 24 h, et corriger le serveur n'y change rien
  // puisque son navigateur ne le rappelle jamais. Changer l'adresse crée une
  // nouvelle entrée et le tire d'affaire sans rien lui demander. À
  // incrémenter si un tel épisode se reproduit.
  const reponse = await fetch(`/api/resolve?v=2&url=${encodeURIComponent(url)}`);
  // Lever plutôt que rendre `null` : un relais injoignable et un lien sans
  // coordonnées appellent deux messages différents. Les confondre a
  // réellement coûté un diagnostic — « aucune coordonnée » accusait le lien
  // alors que la panne était ailleurs.
  if (!reponse.ok) throw new Error(`resolve ${reponse.status}`);
  const charge = await reponse.json();
  return Array.isArray(charge.latlon)
    ? validerLatLon(charge.latlon[0], charge.latlon[1])
    : null;
}

// Même raison que `generation` pour les clics : la résolution d'un lien court
// passe par le réseau, donc un premier collage peut aboutir après un second.
// Sans ce compteur, le lien le plus lent déplacerait la carte en dernier.
let generationLien = 0;

// Un lien copié depuis une barre d'adresse arrive parfois sans son schéma.
// Le rejeter pour ça serait gratuit : on le complète quand la suite ressemble
// à un hôte, et on laisse `LIEN_COURT` et `new URL` juger ensuite.
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
    if (monTour !== generationLien) return; // un lien plus récent a pris le relais
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

// Coller suffit à partir : c'est le geste attendu, et le bouton comme la
// touche Entrée restent disponibles. On écrit la valeur soi-même après
// `preventDefault` pour ne pas dépendre de l'ordre entre l'événement de
// collage et la mise à jour du champ par le navigateur.
champLien.addEventListener('paste', (evenement) => {
  const colle = evenement.clipboardData?.getData('text') ?? '';
  if (!colle.trim()) return;
  evenement.preventDefault();
  champLien.value = colle.trim();
  suivreLien(champLien.value);
});
