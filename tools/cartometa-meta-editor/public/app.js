const state = {
  code: null,
  list: [],
  filtered: [],
  selectedIds: new Set(),
  modified: new Set(),
  // Every country code with unpublished edits sitting server-side — not
  // just the currently open one. Without this, switching away from a
  // country you just edited makes the Publish counter show 0 and gives no
  // hint that work is still waiting there.
  pendingCountries: new Set(),
};

// Reflects (or clears) a country's "has unpublished edits" dot in the
// sidebar, and keeps `state.pendingCountries` — the source of truth for the
// unload warning and the publish-confirmation note below — in sync with it.
function setCountryPending(code, pending) {
  if (pending) state.pendingCountries.add(code);
  else state.pendingCountries.delete(code);
  const btn = document.querySelector(`.country-btn[data-code="${CSS.escape(code)}"]`);
  if (!btn) return;
  const existingDot = btn.querySelector('.pending-dot');
  if (pending && !existingDot) {
    const dot = document.createElement('span');
    dot.className = 'pending-dot';
    dot.title = 'Unpublished edits';
    btn.appendChild(dot);
  } else if (!pending && existingDot) {
    existingDot.remove();
  }
}

// A closed terminal, a sleeping laptop, or a crashed process must not look
// like "nothing happened" — drafts on disk protect the data itself (see
// server.js), this warns before the tab closes in the first place.
window.addEventListener('beforeunload', (e) => {
  if (state.pendingCountries.size > 0) {
    e.preventDefault();
    e.returnValue = '';
  }
});

// The row a range (Shift+click) extends from — the last row clicked without
// Shift. `null` until the first click, and reset whenever the country
// changes (a stale id from another country's list would just fail to be
// found below and fall back to a plain single selection, but resetting
// makes that explicit rather than incidental).
let selectionAnchorId = null;

// Each pending debounced save is keyed by what it targets (a single meta id,
// or a bulk field + selection), not by a single shared slot: an edit to a
// DIFFERENT meta/selection must never cancel one still in flight for another
// (that used to happen with one shared timer, silently dropping the earlier
// edit). `flushPendingSaves` also lets Publish wait for all of them instead
// of racing a save that hasn't fired yet.
const pendingSaves = new Map(); // key -> { timer, fire }

function schedule(key, fire, { immediate = false } = {}) {
  const existing = pendingSaves.get(key);
  if (existing) clearTimeout(existing.timer);
  if (immediate) {
    pendingSaves.delete(key);
    return fire();
  }
  const timer = setTimeout(() => {
    pendingSaves.delete(key);
    fire();
  }, 400);
  pendingSaves.set(key, { timer, fire });
  return undefined;
}

function flushPendingSaves() {
  const pending = [...pendingSaves.values()];
  pendingSaves.clear();
  return Promise.all(pending.map(({ timer, fire }) => {
    clearTimeout(timer);
    return fire();
  }));
}

async function loadCountries() {
  const res = await fetch('/api/countries');
  const countries = await res.json();
  const list = document.getElementById('country-list');
  list.innerHTML = '';
  if (countries.error) {
    list.textContent = countries.error;
    return;
  }
  // The server already knows which countries have an open session with
  // edits, or a leftover draft from a run that never got published — this
  // is what seeds the sidebar dots before you've even opened those
  // countries in this run.
  state.pendingCountries = new Set(countries.filter((c) => c.pending).map((c) => c.code));
  countries.forEach((c) => {
    const btn = document.createElement('button');
    btn.className = 'country-btn' + (c.code === state.code ? ' active' : '');
    btn.dataset.code = c.code;
    btn.textContent = `${c.code} · ${c.count} metas`;
    if (c.pending) {
      const dot = document.createElement('span');
      dot.className = 'pending-dot';
      dot.title = 'Unpublished edits';
      btn.appendChild(dot);
    }
    btn.onclick = () => loadCountry(c.code);
    list.appendChild(btn);
  });
}

async function loadCategories() {
  const res = await fetch('/api/categories');
  const categories = await res.json();
  document.getElementById('category-list').innerHTML = categories
    .map((c) => `<option value="${c}">`)
    .join('');
  const filterSel = document.getElementById('filter-category');
  filterSel.innerHTML =
    '<option value="">Category (all)</option>' +
    categories.map((c) => `<option value="${c}">${c}</option>`).join('');
}

// Rough, human "X ago" for the draft-resumed banner — precision doesn't
// matter here, just enough to tell "a minute ago" from "yesterday".
function formatRelativeTime(isoString) {
  const minutes = Math.round((Date.now() - new Date(isoString).getTime()) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(isoString).toLocaleString();
}

async function loadCountry(code) {
  document.getElementById('list-panel').hidden = false;
  document.getElementById('editor').hidden = false;
  document.getElementById('meta-list').innerHTML = '<div class="list-loading">Loading…</div>';
  document.getElementById('status-bar').textContent = '';

  const res = await fetch(`/api/countries/${code}`);
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || 'Loading error');
    return;
  }
  state.code = code;
  state.list = data.metas;
  state.filtered = state.list;
  state.selectedIds = new Set();
  state.modified = new Set();
  selectionAnchorId = null;

  document.querySelectorAll('.country-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.code === code);
  });

  if (data.draftResumedAt) {
    document.getElementById('status-bar').textContent =
      `↻ Resumed unpublished edits from ${formatRelativeTime(data.draftResumedAt)} — remember to Publish.`;
  }

  populateDifficultyFilter();
  renderList();
  renderEditor();
  updatePublishBtn();
}

function populateDifficultyFilter() {
  const diffs = new Set(state.list.map((m) => m.difficulty).filter(Boolean));
  const sel = document.getElementById('filter-difficulty');
  sel.innerHTML =
    '<option value="">Difficulty (all)</option>' +
    [...diffs].map((d) => `<option value="${d}">${d}</option>`).join('');
}

function applyFilters() {
  const q = document.getElementById('search-input').value.trim().toLowerCase();
  const categoryVal = document.getElementById('filter-category').value;
  const diffVal = document.getElementById('filter-difficulty').value;
  state.filtered = state.list.filter((m) => {
    if (categoryVal && m.category !== categoryVal) return false;
    if (diffVal && m.difficulty !== diffVal) return false;
    if (q && !(m.id.toLowerCase().includes(q) || (m.title || '').toLowerCase().includes(q))) return false;
    return true;
  });
  renderList();
}

function renderList() {
  const container = document.getElementById('meta-list');
  container.innerHTML = '';
  state.filtered.forEach((m) => {
    const row = document.createElement('div');
    row.className = 'meta-row'
      + (state.selectedIds.has(m.id) ? ' selected' : '')
      + (state.modified.has(m.id) ? ' modified' : '');

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'meta-checkbox';
    checkbox.checked = state.selectedIds.has(m.id);
    checkbox.onclick = (e) => {
      e.stopPropagation();
      if (checkbox.checked) state.selectedIds.add(m.id);
      else state.selectedIds.delete(m.id);
      selectionAnchorId = m.id;
      renderList();
      renderEditor();
    };
    row.appendChild(checkbox);

    if (m.image) {
      const img = document.createElement('img');
      img.className = 'meta-thumb';
      img.src = `/api/image?path=${encodeURIComponent(m.image)}`;
      img.alt = '';
      row.appendChild(img);
    } else {
      const placeholder = document.createElement('div');
      placeholder.className = 'meta-thumb meta-thumb-empty';
      row.appendChild(placeholder);
    }

    const textWrap = document.createElement('div');
    textWrap.className = 'meta-row-text';
    const title = document.createElement('div');
    title.className = 'meta-row-title';
    title.textContent = m.title || '(untitled)';
    const sub = document.createElement('div');
    sub.className = 'meta-row-sub';
    sub.textContent = `${m.id} · ${m.tier || ''}${m.difficulty ? ' · ' + m.difficulty : ''}`;
    textWrap.appendChild(title);
    textWrap.appendChild(sub);
    row.appendChild(textWrap);

    // Plain click = exclusive selection. Ctrl/Cmd+click = add/remove from
    // selection. Shift+click = range from the last non-Shift click (the
    // anchor) to this row, over the currently visible (filtered) order —
    // same convention as a file manager. It replaces the selection rather
    // than adding to it, and leaves the anchor where it was so a further
    // Shift+click keeps extending/shrinking from the same starting point.
    row.onclick = (e) => {
      if (e.shiftKey && selectionAnchorId != null) {
        const anchorIndex = state.filtered.findIndex((x) => x.id === selectionAnchorId);
        const clickedIndex = state.filtered.findIndex((x) => x.id === m.id);
        if (anchorIndex === -1) {
          // The anchor row isn't in the current (filtered) list anymore —
          // nothing sane to extend from, so fall back to a plain click.
          state.selectedIds = new Set([m.id]);
          selectionAnchorId = m.id;
        } else {
          const [start, end] = anchorIndex <= clickedIndex
            ? [anchorIndex, clickedIndex]
            : [clickedIndex, anchorIndex];
          state.selectedIds = new Set(state.filtered.slice(start, end + 1).map((x) => x.id));
        }
      } else if (e.ctrlKey || e.metaKey) {
        if (state.selectedIds.has(m.id)) state.selectedIds.delete(m.id);
        else state.selectedIds.add(m.id);
        selectionAnchorId = m.id;
      } else {
        state.selectedIds = new Set([m.id]);
        selectionAnchorId = m.id;
      }
      renderList();
      renderEditor();
    };

    container.appendChild(row);
  });
}

function selectedMetas() {
  return state.list.filter((m) => state.selectedIds.has(m.id));
}

function commonValue(selected, key) {
  const vals = new Set(selected.map((m) => m[key] || ''));
  return vals.size === 1 ? [...vals][0] : '';
}

function renderEditor() {
  const selected = selectedMetas();
  const panel = document.getElementById('single-panel');
  const title = document.getElementById('editor-title');

  if (selected.length === 0) {
    panel.hidden = true;
    title.textContent = 'Select one or more metas from the list';
    return;
  }

  panel.hidden = false;
  const isMulti = selected.length > 1;
  title.textContent = isMulti ? `${selected.length} metas selected` : selected[0].title || selected[0].id;
  renderForm(selected, isMulti);
}

function renderForm(selected, isMulti) {
  const idField = document.getElementById('f-id');
  const titleField = document.getElementById('f-title');
  const catField = document.getElementById('f-category');
  const diffField = document.getElementById('f-difficulty');
  const sourceField = document.getElementById('f-source');
  const descField = document.getElementById('f-description');

  idField.value = isMulti ? `${selected.length} selected` : selected[0].id;

  titleField.disabled = isMulti;
  descField.disabled = isMulti;
  titleField.value = isMulti ? '' : selected[0].title || '';
  descField.value = isMulti ? '' : selected[0].description || '';
  titleField.placeholder = isMulti ? 'Not editable in multi-selection' : 'Meta title';
  descField.placeholder = isMulti ? 'Not editable in multi-selection' : 'Meta description';

  catField.value = commonValue(selected, 'category');
  diffField.value = commonValue(selected, 'difficulty');
  sourceField.value = commonValue(selected, 'source_url');
  catField.placeholder = isMulti ? 'Different values — type to overwrite all' : 'e.g. car, architecture…';
  sourceField.placeholder = isMulti ? 'Different values — type to overwrite all' : 'https://…';

  const img = document.getElementById('preview-image');
  const noImg = document.getElementById('no-image');
  const info = document.getElementById('readonly-info');

  if (isMulti) {
    img.hidden = true;
    noImg.hidden = false;
    noImg.textContent = `${selected.length} metas selected`;
    info.innerHTML = '';
    return;
  }

  const m = selected[0];
  if (m.image) {
    img.src = `/api/image?path=${encodeURIComponent(m.image)}`;
    img.hidden = false;
    noImg.hidden = true;
  } else {
    img.hidden = true;
    noImg.hidden = false;
    noImg.textContent = 'No image';
  }

  const rows = [
    ['country', m.country],
    ['tier', m.tier],
    ['origin', m.origin],
    ['description_origin', m.description_origin],
    ['extracted_at', m.extracted_at],
    ['maps_url', m.maps_url || '—'],
    ['maps_latlon', m.maps_latlon ? JSON.stringify(m.maps_latlon) : '—'],
  ];
  info.innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v ?? '—'}</dd>`).join('');
}

// --- Save: single meta selected -> full PUT on the object.
// Country, id, and values are captured at typing time (not when the
// debounce fires), so a request never targets the wrong country/meta if
// you switched selection in the meantime (this is what used to cause the
// occasional "Meta not found" error).
async function pushSingle(code, id, payload) {
  const res = await fetch(`/api/countries/${code}/metas/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!data.ok) {
    document.getElementById('status-bar').textContent = `❌ ${data.error}`;
    return;
  }
  setCountryPending(code, true);
  if (state.code !== code) return; // country changed in the meantime, ignore silently
  const m = state.list.find((x) => x.id === id);
  if (m) Object.assign(m, payload);
  state.modified.add(id);
  updatePublishBtn();
  renderList();
}

function scheduleSingleSave({ immediate = false } = {}) {
  const selected = selectedMetas();
  if (selected.length !== 1) return;
  const code = state.code;
  const id = selected[0].id;
  const payload = {
    title: document.getElementById('f-title').value,
    description: document.getElementById('f-description').value,
    category: document.getElementById('f-category').value,
    difficulty: document.getElementById('f-difficulty').value || undefined,
    source_url: document.getElementById('f-source').value,
  };
  // Keyed by meta id: switching to another meta and typing there must not
  // cancel this meta's still-pending save (see the comment on `pendingSaves`).
  schedule(`single:${id}`, () => pushSingle(code, id, payload), { immediate });
}

// --- Save: multiple metas selected -> bulk PUT, one field at a time.
// Same principle: country + id list + value are captured at typing time,
// not re-read from live state when the request actually fires.
async function pushBulk(code, ids, key, value, fields) {
  const res = await fetch(`/api/countries/${code}/metas/bulk`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids, fields }),
  });
  const data = await res.json();
  if (!data.ok) {
    document.getElementById('status-bar').textContent = `❌ ${data.error}`;
    return;
  }
  setCountryPending(code, true);
  if (state.code !== code) return;
  ids.forEach((id) => {
    const m = state.list.find((x) => x.id === id);
    if (m) m[key] = key === 'difficulty' ? value || undefined : value;
    state.modified.add(id);
  });
  updatePublishBtn();
  renderList();
  document.getElementById('status-bar').textContent = `✅ ${key} applied to ${data.applied} meta(s). Remember to Publish.`;
}

function scheduleBulkSave(key, elId, { immediate = false } = {}) {
  const selected = selectedMetas();
  if (selected.length <= 1) return;
  const code = state.code;
  const ids = selected.map((m) => m.id);
  const value = document.getElementById(elId).value;
  const fields = { [key]: key === 'difficulty' ? value || '' : value };

  // Keyed by field + the exact selection: changing the selection and editing
  // the same field again must not cancel the previous selection's still-
  // pending save (same reasoning as the single-meta case above).
  const saveKey = `bulk:${key}:${ids.slice().sort().join(',')}`;
  schedule(saveKey, () => pushBulk(code, ids, key, value, fields), { immediate });
}

// Router: depending on how many metas are selected at typing time, save
// either as a single update or a bulk update.
function onFieldChange(key, elId, { immediate = false } = {}) {
  const selected = selectedMetas();
  if (selected.length <= 1) {
    scheduleSingleSave({ immediate });
  } else {
    scheduleBulkSave(key, elId, { immediate });
  }
}

document.getElementById('f-title').addEventListener('input', () => onFieldChange('title', 'f-title'));
document.getElementById('f-description').addEventListener('input', () => onFieldChange('description', 'f-description'));
document.getElementById('f-category').addEventListener('input', () => onFieldChange('category', 'f-category'));
document.getElementById('f-source').addEventListener('input', () => onFieldChange('source_url', 'f-source'));
document.getElementById('f-difficulty').addEventListener('change', () =>
  onFieldChange('difficulty', 'f-difficulty', { immediate: true })
);

document.getElementById('select-all-checkbox').onchange = (e) => {
  if (e.target.checked) {
    state.filtered.forEach((m) => state.selectedIds.add(m.id));
  } else {
    state.filtered.forEach((m) => state.selectedIds.delete(m.id));
  }
  renderList();
  renderEditor();
};

function updatePublishBtn() {
  const btn = document.getElementById('publish-btn');
  btn.textContent = `Publish (${state.modified.size})`;
  btn.disabled = state.modified.size === 0;
}

document.getElementById('search-input').oninput = applyFilters;
document.getElementById('filter-category').onchange = applyFilters;
document.getElementById('filter-difficulty').onchange = applyFilters;

// Builds the confirmation modal's content from the CURRENT state.modified —
// callers must flush pending debounced saves first, so what's shown here is
// exactly what a Confirm click is about to publish, not a stale preview of
// it.
function openPublishModal() {
  const modifiedMetas = [...state.modified]
    .map((id) => state.list.find((m) => m.id === id))
    .filter(Boolean);

  document.getElementById('publish-modal-summary').textContent =
    `You're about to open a Pull Request for ${state.code} with ${modifiedMetas.length} ` +
    `modified meta${modifiedMetas.length === 1 ? '' : 's'}:`;

  const list = document.getElementById('publish-modal-list');
  list.innerHTML = '';
  modifiedMetas.forEach((m) => {
    const li = document.createElement('li');
    li.textContent = `${m.title || '(untitled)'} — ${m.id}`;
    list.appendChild(li);
  });

  // Publish only ever covers the currently open country — if edits are
  // still waiting in others, say so now, at the moment it's most likely to
  // be forgotten, not silently.
  const otherPending = [...state.pendingCountries].filter((c) => c !== state.code);
  const note = document.getElementById('publish-modal-other-pending');
  if (otherPending.length > 0) {
    note.hidden = false;
    note.textContent = `Note: ${otherPending.join(', ')} also ${otherPending.length > 1 ? 'have' : 'has'} ` +
      `unpublished edits. This will NOT include ${otherPending.length > 1 ? 'them' : 'it'} — ` +
      `open ${otherPending.length > 1 ? 'them' : 'it'} separately to publish those too.`;
  } else {
    note.hidden = true;
  }

  document.getElementById('publish-modal').hidden = false;
}

function closePublishModal() {
  document.getElementById('publish-modal').hidden = true;
}

document.getElementById('publish-modal-cancel').onclick = closePublishModal;
document.getElementById('publish-modal').addEventListener('click', (e) => {
  if (e.target.id === 'publish-modal') closePublishModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !document.getElementById('publish-modal').hidden) closePublishModal();
});

async function doPublish() {
  const btn = document.getElementById('publish-btn');
  const statusBar = document.getElementById('status-bar');
  btn.disabled = true;
  statusBar.textContent = 'Publishing… (branch + commit + push + PR)';

  const res = await fetch(`/api/countries/${state.code}/publish`, { method: 'POST' });
  const data = await res.json();
  if (data.ok) {
    statusBar.innerHTML = `✅ PR created on <code>${data.branch}</code> → <a href="${data.prUrl}" target="_blank">${data.prUrl}</a>`;
    state.modified.clear();
    setCountryPending(state.code, false);
    renderList();
    updatePublishBtn();
  } else {
    statusBar.textContent = `❌ ${data.error}`;
    btn.disabled = false;
  }
}

document.getElementById('publish-modal-confirm').onclick = () => {
  closePublishModal();
  doPublish();
};

document.getElementById('publish-btn').onclick = async () => {
  const btn = document.getElementById('publish-btn');
  const statusBar = document.getElementById('status-bar');
  btn.disabled = true;

  // A save can still be debounced (within its 400ms window) at the moment
  // Publish is clicked — e.g. clicking right after the last keystroke.
  // Flushing BEFORE building the confirmation modal (rather than after
  // confirming) is what makes that modal's list trustworthy: it always
  // reflects exactly what's about to be published, never a stale preview.
  statusBar.textContent = 'Saving pending edits…';
  await flushPendingSaves();
  statusBar.textContent = '';
  btn.disabled = state.modified.size === 0;

  if (state.modified.size === 0) return;
  openPublishModal();
};

loadCountries();
loadCategories();
