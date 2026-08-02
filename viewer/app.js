const etat = {
  manifeste: null,
  index: [],
  pays: new Map(),   // code pays -> {metas, geometries}
  resultats: [],
  categorie: '',
  recherche: '',
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
  const { lng: lon, lat } = evenement.latlng;
  const generationDuClic = ++generation;
  document.getElementById('accueil').hidden = true;
  document.getElementById('filtres').hidden = false;
  afficherSquelettes();
  surlignage.clearLayers();
  let resultats;
  try {
    resultats = await interroger(lon, lat);
  } catch (erreur) {
    // Sans ce filet, un pays qui échoue à charger laisse la galerie bloquée
    // sur les squelettes, sans que le visiteur sache que quelque chose a échoué.
    if (generationDuClic !== generation) return; // un clic plus récent a pris le relais
    document.getElementById('galerie').innerHTML =
      '<p id="vide">Could not load metas for this area.</p>';
    return;
  }
  // Ce clic n'est plus le plus récent : son résultat est périmé, on l'ignore.
  if (generationDuClic !== generation) return;
  etat.resultats = resultats;
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

function afficherSquelettes() {}
function rendre() { console.debug(etat.resultats.length, 'résultats'); }
