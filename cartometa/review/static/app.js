const map = L.map('map').setView([52, 19], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 18,
}).addTo(map);

let queue = [];
let index = 0;
let total = 0;
let reviewed = 0;
// Chaque entrée est { type: 'decision', id } ou { type: 'pass' }, dans
// l'ordre exact des actions — U doit défaire précisément la dernière,
// qu'il s'agisse d'une décision persistée ou d'un simple passage local.
let history = [];
let layers = L.layerGroup().addTo(map);
let busy = false; // évite les doubles soumissions pendant qu'une requête est en vol

// Décalage accumulé sur la méta affichée, en degrés. Il n'est jamais
// persisté seul : il part au serveur avec la validation (A). Remis à zéro
// à chaque changement de méta.
let offset = { lon: 0, lat: 0 };

const NUDGE_KM = 5;        // pas fin, ordre de grandeur de la précision visée
const NUDGE_KM_COARSE = 25; // avec Maj
const KM_PER_DEG_LAT = 111.32;

// Les flèches pilotent le polygone, pas la carte.
map.keyboard.disable();

function kmToDegrees(km, latitude) {
  const dlat = km / KM_PER_DEG_LAT;
  // Un degré de longitude rétrécit avec la latitude : sans ce cosinus, un
  // pas « 5 km vers l'est » vaudrait 5 km à l'équateur et 2,5 km à 60°.
  const dlon = km / (KM_PER_DEG_LAT * Math.cos((latitude * Math.PI) / 180));
  return { dlat, dlon };
}

function translateGeometry(geometry, dlon, dlat) {
  const move = (coords) =>
    typeof coords[0] === 'number'
      ? [coords[0] + dlon, coords[1] + dlat]
      : coords.map(move);
  return { type: geometry.type, coordinates: move(geometry.coordinates) };
}

function shiftedGeometry(item) {
  if (!item.geometry) return null;
  if (!offset.lon && !offset.lat) return item.geometry;
  return translateGeometry(item.geometry, offset.lon, offset.lat);
}

function centroidLatitude(geometry) {
  // Latitude approximative, prise au milieu de la bounding box : elle ne
  // sert qu'à dimensionner le pas en longitude.
  let min = 90;
  let max = -90;
  const scan = (coords) => {
    if (typeof coords[0] === 'number') {
      min = Math.min(min, coords[1]);
      max = Math.max(max, coords[1]);
    } else {
      coords.forEach(scan);
    }
  };
  scan(geometry.coordinates);
  return (min + max) / 2;
}

function nudge(eastKm, northKm) {
  const item = current();
  if (!item || !item.geometry || busy) return;
  const latitude = centroidLatitude(item.geometry);
  if (eastKm) offset.lon += kmToDegrees(eastKm, latitude).dlon;
  if (northKm) offset.lat += kmToDegrees(northKm, latitude).dlat;
  drawGeometry(item, { keepView: true });
}

function resetOffset() {
  const item = current();
  if (!item || busy || (!offset.lon && !offset.lat)) return;
  offset = { lon: 0, lat: 0 };
  drawGeometry(item, { keepView: true });
}

function offsetLabel(item) {
  if (!offset.lon && !offset.lat) return '';
  const latitude = centroidLatitude(item.geometry);
  const perDegLon = KM_PER_DEG_LAT * Math.cos((latitude * Math.PI) / 180);
  const east = offset.lon * perDegLon;
  const north = offset.lat * KM_PER_DEG_LAT;
  const fmt = (km, positive, negative) =>
    Math.abs(km) < 0.05 ? '' : `${Math.abs(km).toFixed(0)} km ${km > 0 ? positive : negative}`;
  return ['décalé', fmt(north, 'nord', 'sud'), fmt(east, 'est', 'ouest')]
    .filter(Boolean)
    .join(' ');
}

function showError(message) {
  const el = document.getElementById('error');
  el.textContent = message;
  el.hidden = false;
}

function clearError() {
  const el = document.getElementById('error');
  el.hidden = true;
  el.textContent = '';
}

async function loadQueue() {
  const response = await fetch('/api/queue');
  const data = await response.json();
  queue = data.items;
  total = data.total;
  reviewed = data.reviewed;
  index = 0;
  history = [];
  render();
}

function current() {
  return queue[index];
}

function render() {
  const item = current();
  if (!item) {
    document.getElementById('progress').textContent = `Terminé — ${total} métas revues`;
    document.getElementById('title').textContent = '';
    layers.clearLayers();
    return;
  }
  document.getElementById('progress').textContent =
    `${reviewed + index} / ${total}`;
  document.getElementById('confidence').textContent =
    `confiance ${item.confidence.toFixed(2)} — ${item.tier}`;
  document.getElementById('image').src = item.image || '';
  document.getElementById('title').textContent = item.title;
  document.getElementById('description').textContent = item.description;
  document.getElementById('warnings').textContent = item.warnings.join(' · ');
  document.getElementById('source-link').href = item.source_url;

  // Le rayon ne peut aider que sur un spot qui a déjà une géométrie à
  // recentrer/redimensionner : sans géométrie, il n'y a rien à corriger.
  // Le serveur applique la même règle indépendamment (défense en
  // profondeur) : cet affichage n'est qu'un confort, pas le seul garde-fou.
  const canApplyRadius = item.tier === 'spot' && Boolean(item.geometry);
  document.getElementById('radius-row').hidden = !canApplyRadius;

  drawGeometry(item, { keepView: false });
}

function drawGeometry(item, { keepView }) {
  layers.clearLayers();
  const moved = offset.lon || offset.lat;
  if (item.geometry) {
    if (moved) {
      // Position d'origine en pointillé : sans elle, on perd la référence
      // de ce que le décalage est en train de corriger.
      L.geoJSON(item.geometry, {
        color: '#c1283a', weight: 1, opacity: 0.4, dashArray: '4 4', fill: false,
      }).addTo(layers);
    }
    const shape = L.geoJSON(shiftedGeometry(item), { color: '#c1283a', weight: 2 }).addTo(layers);
    if (!keepView) map.fitBounds(shape.getBounds(), { padding: [30, 30], maxZoom: 9 });
  }
  if (item.latlon) {
    // Vérité terrain : elle ne bouge pas avec le polygone, c'est la cible.
    L.circleMarker([item.latlon[0], item.latlon[1]], {
      radius: 6, color: '#0057d9', fillOpacity: 0.9,
    }).addTo(layers);
  }
  const row = document.getElementById('offset-row');
  row.textContent = moved ? `${offsetLabel(item)} — A pour enregistrer, 0 pour annuler` : '';
  row.hidden = !moved;
}

async function postJSON(path, body) {
  let response;
  try {
    response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (err) {
    throw new Error(`connexion au serveur perdue : ${err.message}`);
  }
  let data = {};
  try {
    data = await response.json();
  } catch (_err) {
    // pas de corps JSON exploitable : on retombe sur le code HTTP
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `erreur HTTP ${response.status}`);
  }
  return data;
}

async function decide(status, radiusKm) {
  const item = current();
  if (!item || busy) return;
  // Un décalage en attente transforme la validation en correction : c'est la
  // géométrie déplacée, telle qu'affichée, qui doit être enregistrée.
  const pendingOffset = offset.lon || offset.lat ? [offset.lon, offset.lat] : null;
  const body = { id: item.id, status, radius_km: radiusKm ?? null };
  // Un rejet reste un rejet : on ne convertit qu'une validation.
  if (pendingOffset && !radiusKm && status === 'validé') {
    body.status = 'corrigé';
    body.offset_deg = pendingOffset;
  }
  busy = true;
  try {
    await postJSON('/api/decision', body);
    clearError();
    history.push({ type: 'decision', id: item.id });
    index += 1;
    offset = { lon: 0, lat: 0 };
    render();
  } catch (err) {
    // Échec : on ne fait PAS avancer l'index et on ne persiste rien côté
    // historique local — la méta reste affichée, l'erreur est visible.
    showError(`Décision non enregistrée pour ${item.id} : ${err.message}`);
  } finally {
    busy = false;
  }
}

async function undo() {
  if (!history.length || busy) return;
  const last = history[history.length - 1];
  if (last.type === 'pass') {
    // Un passage n'a jamais rien persisté côté serveur : on le défait
    // localement, sans appel réseau.
    history.pop();
    index = Math.max(0, index - 1);
    offset = { lon: 0, lat: 0 };
    render();
    return;
  }
  busy = true;
  try {
    await postJSON('/api/undo', { id: last.id });
    clearError();
    history.pop();
    index = Math.max(0, index - 1);
    offset = { lon: 0, lat: 0 };
    render();
  } catch (err) {
    showError(`Annulation impossible pour ${last.id} : ${err.message}`);
  } finally {
    busy = false;
  }
}

const ARROWS = {
  ArrowUp: [0, 1], ArrowDown: [0, -1], ArrowRight: [1, 0], ArrowLeft: [-1, 0],
};

document.addEventListener('keydown', (event) => {
  if (event.target.tagName === 'INPUT' && event.key !== 'Enter') return;
  const arrow = ARROWS[event.key];
  if (arrow) {
    event.preventDefault(); // sinon la page défile
    const step = event.shiftKey ? NUDGE_KM_COARSE : NUDGE_KM;
    nudge(arrow[0] * step, arrow[1] * step);
    return;
  }
  switch (event.key.toLowerCase()) {
    case '0': resetOffset(); break;
    case 'a': decide('validé'); break;
    case 'r': decide('rejeté'); break;
    case ' ':
      event.preventDefault();
      if (!busy && current()) {
        history.push({ type: 'pass' });
        index += 1;
        offset = { lon: 0, lat: 0 };
        render();
      }
      break;
    case 'u': undo(); break;
    case 'enter':
      if (current() && current().tier === 'spot' && current().geometry) {
        decide('corrigé', Number(document.getElementById('radius').value));
      }
      break;
  }
});

const radius = document.getElementById('radius');
radius.addEventListener('input', () => {
  document.getElementById('radius-value').textContent = radius.value;
});

loadQueue();
