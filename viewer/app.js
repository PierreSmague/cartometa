const map = L.map('map').setView([52, 19], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 18,
}).addTo(map);

let index = [];
let geometries = {};
let matches = [];
const highlight = L.layerGroup().addTo(map);

Promise.all([
  fetch('data/index.json').then((r) => r.json()),
  fetch('data/geometries.json').then((r) => r.json()),
]).then(([loadedIndex, loadedGeometries]) => {
  index = loadedIndex;
  geometries = loadedGeometries;
});

function insideRing(lon, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function insidePolygon(lon, lat, rings) {
  if (!insideRing(lon, lat, rings[0])) return false;
  for (let i = 1; i < rings.length; i += 1) {
    if (insideRing(lon, lat, rings[i])) return false; // trou
  }
  return true;
}

function contains(geometry, lon, lat) {
  if (geometry.type === 'Polygon') return insidePolygon(lon, lat, geometry.coordinates);
  return geometry.coordinates.some((rings) => insidePolygon(lon, lat, rings));
}

function query(lon, lat) {
  // Filtre bbox d'abord : élimine la quasi-totalité des candidats en une passe.
  return index.filter((entry) => {
    const [minLon, minLat, maxLon, maxLat] = entry.bbox;
    if (lon < minLon || lon > maxLon || lat < minLat || lat > maxLat) return false;
    return contains(geometries[entry.id], lon, lat);
  });
}

function visible() {
  const term = document.getElementById('search').value.trim().toLowerCase();
  const category = document.getElementById('category').value;
  return matches.filter((entry) => {
    if (category && entry.category !== category) return false;
    if (!term) return true;
    return (entry.title + ' ' + entry.description).toLowerCase().includes(term);
  });
}

function render() {
  const list = document.getElementById('results');
  const entries = visible();
  document.getElementById('hint').textContent = entries.length
    ? `${entries.length} méta(s) — de la plus spécifique à la plus générale`
    : 'Aucune méta pour ce point.';
  list.innerHTML = '';
  for (const entry of entries) {
    const item = document.createElement('li');
    item.innerHTML =
      `<span class="badge">${entry.country}</span> ` +
      `<span class="badge">${entry.category}</span> <strong>${entry.title}</strong>` +
      `<div>${entry.description}</div>` +
      (entry.image ? `<img loading="lazy" src="../${entry.image}" alt="">` : '') +
      `<a href="${entry.source_url}" target="_blank" rel="noopener">source</a>`;
    item.addEventListener('mouseenter', () => {
      highlight.clearLayers();
      L.geoJSON(geometries[entry.id], { color: '#c1283a', weight: 2 }).addTo(highlight);
    });
    list.appendChild(item);
  }
}

map.on('click', (event) => {
  const started = performance.now();
  // index est déjà trié par surface croissante : du plus spécifique au plus général.
  matches = query(event.latlng.lng, event.latlng.lat);
  console.debug(`requête en ${(performance.now() - started).toFixed(1)} ms`);
  highlight.clearLayers();
  render();
});

document.getElementById('search').addEventListener('input', render);
document.getElementById('category').addEventListener('change', render);
