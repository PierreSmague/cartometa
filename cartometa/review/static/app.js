import { getJSON, postJSON } from './api.js';
import { Sketch } from './sketch.js';
import { closeManualForm, isManualFormOpen, openManualForm } from './manual.js';

const map = L.map('map').setView([52, 19], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 18,
}).addTo(map);

// Les touches pilotent le tracé, pas la carte.
map.keyboard.disable();

const layers = L.layerGroup().addTo(map);
const sketch = new Sketch(map, layers);

let queue = [];
let index = 0;
let total = 0;
// Fixé une fois pour la session par loadQueue() : la file ne contient que
// les métas non décidées, donc c'est index qui porte la progression —
// ne jamais l'incrémenter/décrémenter dans decide()/undo().
let done = 0;
let busy = false;
// Chaque entrée est { type: 'decision', id } ou { type: 'pass' }, dans
// l'ordre exact des actions — U doit défaire précisément la dernière.
let history = [];

const current = () => queue[index];

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
  const data = await getJSON('/api/queue');
  queue = data.items;
  total = data.total;
  done = data.done;
  index = 0;
  history = [];
  render();
}

function render() {
  const item = current();
  layers.clearLayers();
  if (!item) {
    // Même formule que le compteur courant : done + queue.length === total
    // par construction, dans les deux modes. `done` (store.build_queue) est
    // le nombre de métas décidées ABSENTES de la file rendue — par défaut
    // ça compte toutes les décidées, sous --all ça retombe à 0 puisqu'elles
    // y sont toutes rouvertes — donc à la file épuisée ce nombre tombe
    // toujours juste sur total. Imprécision assumée : un passage (Espace)
    // compte comme « dépassé », pas comme décidé — c'est une progression
    // dans la file, pas un compte de décisions, et ça reste cohérent avec
    // le compteur ci-dessous.
    document.getElementById('progress').textContent = `Terminé — ${done + index} / ${total}`;
    document.getElementById('title').textContent = '';
    document.getElementById('description').textContent = '';
    document.getElementById('image').removeAttribute('src');
    document.getElementById('sketch-row').hidden = true;
    return;
  }
  document.getElementById('progress').textContent = `${done + index} / ${total}`;
  document.getElementById('context').textContent =
    `${item.category} — ${item.tier}${item.status ? ` — ${item.status}` : ''}`;
  if (item.image) document.getElementById('image').src = item.image;
  else document.getElementById('image').removeAttribute('src');
  document.getElementById('title').textContent = item.title;
  document.getElementById('description').textContent = item.description;
  document.getElementById('source-link').href = item.source_url || '#';

  sketch.reset(item.pieces);
  frame(item);
  loadPiecesGeometry(item);
  draw();
}

async function frame(item) {
  // Tout arrive vierge : le point Maps est le seul repère quand il existe,
  // sinon on cadre le pays pour ne pas laisser la carte au milieu de rien.
  if (item.latlon) {
    map.setView([item.latlon[0], item.latlon[1]], 8);
    return;
  }
  try {
    const geometry = await sketch.ensureCountry();
    // La file a pu avancer pendant l'attente : une méta périmée ne doit
    // pas recadrer la carte affichée pour la méta suivante.
    if (current() !== item) return;
    map.fitBounds(L.geoJSON(geometry).getBounds(), { padding: [20, 20] });
    // La silhouette vient d'arriver : si un morceau `country` était déjà
    // posé (méta rouverte), il n'a rien pu dessiner au draw() synchrone
    // fait avant cet await — il faut redessiner maintenant qu'elle existe.
    draw();
  } catch (err) {
    // Idem : une méta abandonnée ne doit pas lever une alarme sur celle
    // qui est actuellement affichée.
    if (current() !== item) return;
    showError(`Cadrage impossible : ${err.message}`);
  }
}

async function loadPiecesGeometry(item) {
  // Indépendant de frame() : une méta avec un point Maps (`item.latlon`)
  // ne charge jamais la silhouette du pays pour se cadrer, mais peut quand
  // même porter un morceau `country` ou `admin1` posé avant sa réouverture.
  try {
    await sketch.ensurePiecesGeometry();
  } catch (err) {
    if (current() !== item) return;
    showError(`Chargement des morceaux impossible : ${err.message}`);
    return;
  }
  // La file a pu avancer pendant l'attente : ne pas redessiner pour une
  // méta qui n'est plus celle affichée.
  if (current() !== item) return;
  draw();
}

function draw() {
  const item = current();
  layers.clearLayers();
  if (!item) return;
  sketch.render();
  if (item.latlon) {
    // Vérité terrain : elle ne bouge pas, c'est la cible.
    L.circleMarker([item.latlon[0], item.latlon[1]], {
      radius: 6, color: '#0057d9', fillOpacity: 0.9,
    }).addTo(layers);
  }
  const row = document.getElementById('sketch-row');
  row.textContent = sketch.statusLine();
  row.hidden = !row.textContent;
}

async function decide(status) {
  const item = current();
  if (!item || busy) return;
  if (status === 'validé' && sketch.isEmpty) {
    showError('Aucun morceau posé : rien à enregistrer.');
    return;
  }
  busy = true;
  try {
    await postJSON('/api/decision', {
      id: item.id, status, pieces: status === 'validé' ? sketch.pieces : [],
    });
    clearError();
    history.push({ type: 'decision', id: item.id });
    index += 1;
    render();
  } catch (err) {
    // Échec : l'index n'avance pas, la méta reste affichée, l'erreur visible.
    showError(`Décision non enregistrée pour ${item.id} : ${err.message}`);
  } finally {
    busy = false;
  }
}

async function undo() {
  if (!history.length || busy) return;
  const last = history[history.length - 1];
  if (last.type === 'pass') {
    // Un passage n'a rien persisté : on le défait sans appel réseau.
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

function step(offset) {
  if (busy || !current()) return;
  if (offset > 0) {
    history.push({ type: 'pass' });
  } else if (history.length && history[history.length - 1].type === 'pass') {
    // Reculer défait précisément le passage qu'avancer venait de tracer.
    // Si la dernière entrée est une décision, elle est persistée sur
    // disque : seul U peut la défaire, on ne touche pas à l'historique ici.
    history.pop();
  }
  index = Math.min(Math.max(0, index + offset), queue.length);
  render();
}

async function enterMode(mode) {
  if (busy || !current()) return;
  try {
    await sketch.setMode(mode);
    clearError();
  } catch (err) {
    showError(`Mode ${mode} indisponible : ${err.message}`);
  }
  draw();
}

async function addCountry() {
  if (busy || !current()) return;
  try {
    await sketch.addCountry();
    clearError();
  } catch (err) {
    showError(`Polygone du pays indisponible : ${err.message}`);
  }
  draw();
}

function onManualCreated(meta) {
  // La méta créée passe devant : on la trace tout de suite, tant qu'on a
  // sa source sous les yeux.
  queue.splice(index, 0, {
    id: meta.id, title: meta.title, description: meta.description,
    category: meta.category, tier: meta.tier, origin: meta.origin,
    image: meta.image || null, latlon: null, source_url: meta.source_url,
    status: null, pieces: [],
  });
  total += 1;
  render();
}

document.addEventListener('keydown', (event) => {
  if (isManualFormOpen()) {
    if (event.key === 'Escape') closeManualForm();
    return;
  }
  if (event.key === 'Backspace') {
    event.preventDefault();
    sketch.undoLast();
    draw();
    return;
  }
  if (event.key === 'Escape') {
    sketch.leaveMode();
    draw();
    return;
  }
  if (event.key === 'Enter') {
    sketch.closeContour();
    draw();
    return;
  }
  if (event.key === ' ') {
    event.preventDefault();
    step(event.shiftKey ? -1 : 1);
    return;
  }
  switch (event.key.toLowerCase()) {
    case 'd': enterMode('rect'); break;
    case 'c': enterMode('contour'); break;
    case 's': enterMode('admin1'); break;
    case 'e': addCountry(); break;
    case '0': sketch.clear(); draw(); break;
    case 'a': decide('validé'); break;
    case 'r': decide('rejeté'); break;
    case 'u': undo(); break;
    case 'n': openManualForm(onManualCreated); break;
    default: break;
  }
});

map.on('click', (event) => {
  if (busy || !current()) return;
  sketch.onMapClick(event.latlng);
  draw();
});

map.on('mousemove', (event) => {
  if (!sketch.mode) return;
  if (sketch.onMapMove(event.latlng)) draw();
});

loadQueue().catch((err) => showError(`File indisponible : ${err.message}`));
