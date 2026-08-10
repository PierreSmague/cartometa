import { getJSON, postJSON } from './api.js';
import { Sketch } from './sketch.js';
import { closeManualForm, isManualFormOpen, openManualForm } from './manual.js';

const map = L.map('map').setView([52, 19], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 18,
}).addTo(map);

// The keys drive the drawing, not the map.
map.keyboard.disable();

const layers = L.layerGroup().addTo(map);
const sketch = new Sketch(map, layers);

let queue = [];
let index = 0;
let total = 0;
// Set once for the session by loadQueue(): the queue only holds undecided metas,
// so it is index that carries the progress — never increment/decrement this in
// decide()/undo().
let done = 0;
let busy = false;
// Each entry is { type: 'decision', id } or { type: 'pass' }, in the exact order
// of the actions — U has to undo precisely the last one.
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
    // Same formula as the running counter: done + queue.length === total by
    // construction, in both modes. `done` (store.build_queue) is the number of
    // decided metas ABSENT from the returned queue — by default that counts every
    // decided one, under --all it falls back to 0 since they are all reopened there
    // — so once the queue is exhausted this number always lands exactly on total.
    // An accepted imprecision: a pass (Space) counts as "gone past", not as
    // decided — this is progress through the queue, not a count of decisions, and
    // it stays consistent with the counter below.
    document.getElementById('progress').textContent = `Done - ${done + index} / ${total}`;
    document.getElementById('title').textContent = '';
    document.getElementById('description').textContent = '';
    document.getElementById('image').removeAttribute('src');
    document.getElementById('overlay').removeAttribute('src');
    document.getElementById('overlay').hidden = true;
    document.getElementById('sketch-row').hidden = true;
    return;
  }
  document.getElementById('progress').textContent = `${done + index} / ${total}`;
  document.getElementById('context').textContent =
    `${item.category} — ${item.tier}${item.status ? ` — ${item.status}` : ''}`;
  if (item.image) document.getElementById('image').src = item.image;
  else document.getElementById('image').removeAttribute('src');
  const overlay = document.getElementById('overlay');
  // RMRG only: the guide's own region mini-map, i.e. the answer being traced.
  if (item.overlay) { overlay.src = item.overlay; overlay.hidden = false; }
  else { overlay.removeAttribute('src'); overlay.hidden = true; }
  document.getElementById('title').textContent = item.title;
  document.getElementById('description').textContent = item.description;
  document.getElementById('source-link').href = item.source_url || '#';

  sketch.reset(item.pieces);
  frame(item);
  loadPiecesGeometry(item);
  refresh();
}

async function frame(item) {
  // Everything arrives blank: the Maps point is the only landmark when it exists,
  // otherwise we frame the country so as not to leave the map in the middle of
  // nowhere.
  if (item.latlon) {
    map.setView([item.latlon[0], item.latlon[1]], 8);
    return;
  }
  try {
    const geometry = await sketch.ensureCountry();
    // The queue may have moved on while we waited: a stale meta must not reframe
    // the map that is now showing the next one.
    if (current() !== item) return;
    map.fitBounds(L.geoJSON(geometry).getBounds(), { padding: [20, 20] });
    // The silhouette has just arrived: if a `country` piece was already laid down
    // (reopened meta), it could draw nothing during the synchronous draw() made
    // before this await — it has to be redrawn now that the silhouette exists.
    draw();
  } catch (err) {
    // Same thing: an abandoned meta must not raise an alarm about the one
    // currently displayed.
    if (current() !== item) return;
    showError(`Cannot frame the map: ${err.message}`);
  }
}

async function loadPiecesGeometry(item) {
  // Independent of frame(): a meta with a Maps point (`item.latlon`) never loads
  // the country silhouette to frame itself, but can still carry a `country` or
  // `admin1` piece laid down before it was reopened.
  try {
    await sketch.ensurePiecesGeometry();
  } catch (err) {
    if (current() !== item) return;
    showError(`Cannot load the pieces: ${err.message}`);
    return;
  }
  // The queue may have moved on while we waited: do not redraw for a meta that is
  // no longer the one on screen.
  if (current() !== item) return;
  draw();
}

function draw() {
  const item = current();
  layers.clearLayers();
  if (!item) return;
  sketch.render();
  if (item.latlon) {
    // Ground truth: it does not move, it is the target.
    L.circleMarker([item.latlon[0], item.latlon[1]], {
      radius: 6, color: '#0057d9', fillOpacity: 0.9,
    }).addTo(layers);
  }
  const row = document.getElementById('sketch-row');
  row.textContent = sketch.statusLine();
  row.hidden = !row.textContent;
}

function refresh() {
  // To be used as soon as the pieces change. draw() is synchronous and shows the
  // known state right away; if the area is clipped, its preview comes from the
  // server (the only one able to intersect) and a second draw() follows its arrival.
  draw();
  if (!sketch.needsClip()) return;
  const item = current();
  sketch.ensureClip()
    .then(() => { if (current() === item) draw(); })
    .catch((err) => {
      if (current() !== item) return;
      showError(`Cannot clip: ${err.message}`);
      draw();
    });
}

async function decide(status) {
  const item = current();
  if (!item || busy) return;
  if (status === 'validé' && sketch.isEmpty) {
    showError('No piece laid down: nothing to save.');
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
    // Failure: the index does not advance, the meta stays on screen, the error visible.
    showError(`Decision not saved for ${item.id}: ${err.message}`);
  } finally {
    busy = false;
  }
}

async function undo() {
  if (!history.length || busy) return;
  const last = history[history.length - 1];
  if (last.type === 'pass') {
    // A pass persisted nothing: we undo it without a network call.
    history.pop();
    index = Math.max(0, index - 1);
    render();
    return;
  }
  busy = true;
  try {
    // Une meta importée « proposé » ne doit pas redevenir vierge : U restaure
    // l'état que la file avait chargé (statut et pièces d'origine).
    const item = queue.find((q) => q.id === last.id);
    const payload = { id: last.id };
    if (item && item.status === 'proposé') {
      payload.restore = { status: item.status, pieces: item.pieces };
    }
    await postJSON('/api/undo', payload);
    clearError();
    history.pop();
    index = Math.max(0, index - 1);
    render();
  } catch (err) {
    showError(`Cannot undo ${last.id}: ${err.message}`);
  } finally {
    busy = false;
  }
}

function step(offset) {
  if (busy || !current()) return;
  if (offset > 0) {
    history.push({ type: 'pass' });
  } else if (history.length && history[history.length - 1].type === 'pass') {
    // Going back undoes precisely the pass that going forward had just recorded.
    // If the last entry is a decision, it is persisted on disk: only U can undo it,
    // we do not touch the history here.
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
    showError(`Mode ${mode} unavailable: ${err.message}`);
  }
  draw();
}

async function addCountry() {
  if (busy || !current()) return;
  try {
    await sketch.addCountry();
    clearError();
  } catch (err) {
    showError(`Country polygon unavailable: ${err.message}`);
  }
  refresh();
}

function toggleClip() {
  if (busy || !current()) return;
  sketch.toggleClip();
  clearError();
  refresh();
}

function onManualCreated(meta) {
  // The newly created meta goes to the front: we draw it right away, while its
  // source is still in front of us.
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
    refresh();
    return;
  }
  if (event.key === 'Escape') {
    sketch.leaveMode();
    draw();
    return;
  }
  if (event.key === 'Enter') {
    sketch.closeContour();
    refresh();
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
    case 'f': toggleClip(); break;
    case '0': sketch.clear(); refresh(); break;
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
  refresh();
});

map.on('mousemove', (event) => {
  if (!sketch.mode) return;
  if (sketch.onMapMove(event.latlng)) draw();
});

loadQueue().catch((err) => showError(`Queue unavailable: ${err.message}`));
