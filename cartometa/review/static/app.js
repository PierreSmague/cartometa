const map = L.map('map').setView([52, 19], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 18,
}).addTo(map);

let queue = [];
let index = 0;
let total = 0;
let reviewed = 0;
let history = [];
let layers = L.layerGroup().addTo(map);

async function loadQueue() {
  const response = await fetch('/api/queue');
  const data = await response.json();
  queue = data.items;
  total = data.total;
  reviewed = data.reviewed;
  index = 0;
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

  const isSpot = item.tier === 'spot';
  document.getElementById('radius-row').hidden = !isSpot;

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

async function decide(status, radiusKm) {
  const item = current();
  if (!item) return;
  history.push(item.id);
  await fetch('/api/decision', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: item.id, status, radius_km: radiusKm ?? null }),
  });
  index += 1;
  render();
}

document.addEventListener('keydown', (event) => {
  if (event.target.tagName === 'INPUT' && event.key !== 'Enter') return;
  switch (event.key.toLowerCase()) {
    case 'a': decide('validé'); break;
    case 'r': decide('rejeté'); break;
    case ' ': event.preventDefault(); index += 1; render(); break;
    case 'u':
      if (history.length) {
        history.pop();
        index = Math.max(0, index - 1);
        render();
      }
      break;
    case 'enter':
      if (current() && current().tier === 'spot') {
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
