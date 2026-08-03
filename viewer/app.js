const etat = {
  manifeste: null,
  index: [],
  pays: new Map(),   // code pays -> {metas, geometries}
  resultats: [],
  categorie: '',
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

carte.on('click', async (evenement) => {
  // Sans ce garde-fou, un premier clic après un échec au démarrage efface
  // aussitôt le message d'erreur dans #accueil (hidden = true ci-dessous) et
  // rend une galerie vide sans exception : le visiteur perd la seule
  // explication qu'il aura jamais eue.
  if (!etat.pret) return;
  // `.wrap()` : avec `worldCopyJump`, un clic sur une copie répétée du monde
  // (zoom ≤ 2) porte une longitude hors ±180°, que rien dans `etat.index`
  // (des bbox en ±180°) ne peut jamais recouvrir — un clic pourtant valide
  // ressortirait « aucune méta » sans raison visible.
  const { lng: lon, lat } = evenement.latlng.wrap();
  const generationDuClic = ++generation;
  document.getElementById('accueil').hidden = true;
  document.getElementById('filtres').hidden = false;
  etat.chargement = true;
  etat.erreur = false;
  afficherSquelettes();
  surlignage.clearLayers();
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
  texte.textContent = `${meta.title} `;
  const lien = document.createElement('a');
  lien.href = meta.source_url;
  lien.target = '_blank';
  lien.rel = 'noopener';
  lien.textContent = 'source';
  texte.appendChild(lien);
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

for (const pastille of document.querySelectorAll('.pastille')) {
  pastille.addEventListener('click', () => {
    // Même garde-fou que pour la recherche : voir le commentaire ci-dessus.
    if (etat.chargement || etat.erreur) return;
    for (const autre of document.querySelectorAll('.pastille')) {
      autre.classList.toggle('active', autre === pastille);
    }
    etat.categorie = pastille.dataset.categorie;
    rendre();
  });
}
