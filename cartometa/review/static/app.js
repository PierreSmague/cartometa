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

  layers.clearLayers();
  if (item.geometry) {
    const shape = L.geoJSON(item.geometry, { color: '#c1283a', weight: 2 }).addTo(layers);
    map.fitBounds(shape.getBounds(), { padding: [30, 30], maxZoom: 9 });
  }
  if (item.latlon) {
    // Vérité terrain : hors du polygone, le rejet est immédiat.
    L.circleMarker([item.latlon[0], item.latlon[1]], {
      radius: 6, color: '#0057d9', fillOpacity: 0.9,
    }).addTo(layers);
  }
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
  busy = true;
  try {
    await postJSON('/api/decision', { id: item.id, status, radius_km: radiusKm ?? null });
    clearError();
    history.push({ type: 'decision', id: item.id });
    index += 1;
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
    render();
    return;
  }
  busy = true;
  try {
    await postJSON('/api/undo', { id: last.id });
    clearError();
    history.pop();
    index = Math.max(0, index - 1);
    render();
  } catch (err) {
    showError(`Annulation impossible pour ${last.id} : ${err.message}`);
  } finally {
    busy = false;
  }
}

document.addEventListener('keydown', (event) => {
  if (event.target.tagName === 'INPUT' && event.key !== 'Enter') return;
  switch (event.key.toLowerCase()) {
    case 'a': decide('validé'); break;
    case 'r': decide('rejeté'); break;
    case ' ':
      event.preventDefault();
      if (!busy && current()) {
        history.push({ type: 'pass' });
        index += 1;
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
