import { getJSON, postBytes, postJSON } from './api.js';

const panel = document.getElementById('manual');
const drop = document.getElementById('drop');
const errorLine = document.getElementById('manual-error');
const categorySelect = document.getElementById('manual-category');
const difficultySelect = document.getElementById('manual-difficulty');
const heading = document.getElementById('manual-heading');
const saveButton = document.getElementById('manual-save');

let pendingImage = null;   // Pending blob, sent once the meta has been created
let onDone = null;
// The identifier being edited, or null when creating. It is what tells `save()` which
// route to call — the form itself is the same in both modes.
let editing = null;
// As soon as the human has picked a category, inference goes quiet: suggesting is
// useful, overwriting an explicit choice never is.
let categoryTouched = false;
let inferTimer = null;

export function isManualFormOpen() {
  return !panel.hidden;
}

function openForm({ item, callback }) {
  onDone = callback;
  editing = item ? item.id : null;
  pendingImage = null;
  // On an existing meta the category is already a decision, someone's or an
  // importer's: inference must not overwrite it on the first keystroke.
  categoryTouched = Boolean(item);
  errorLine.textContent = '';
  drop.className = '';
  drop.innerHTML = 'Drop an image here, or paste it with Ctrl+V';
  document.getElementById('manual-title').value = item ? item.title : '';
  document.getElementById('manual-description').value = item ? item.description : '';
  document.getElementById('manual-source').value = item ? (item.source_url || '') : '';
  categorySelect.value = item ? item.category : 'autre';
  difficultySelect.value = item ? (item.difficulty || '') : '';
  heading.textContent = item ? `Edit ${item.id}` : 'New meta';
  saveButton.textContent = item ? 'Save changes' : 'Create';
  panel.hidden = false;
  document.getElementById('manual-title').focus();
}

export function openManualForm(callback) {
  openForm({ item: null, callback });
}

// Same form, prefilled from the meta on screen. Its footprint is untouched: this
// only ever rewrites texts, category and difficulty.
export function openEditForm(item, callback) {
  openForm({ item, callback });
}

function scheduleInference() {
  if (categoryTouched) return;
  clearTimeout(inferTimer);
  inferTimer = setTimeout(async () => {
    const text = `${document.getElementById('manual-title').value} `
      + `${document.getElementById('manual-description').value}`;
    if (!text.trim()) return;
    try {
      const guessed = await getJSON(`/api/category?text=${encodeURIComponent(text)}`);
      // Re-checked after the round trip: the human may have picked in the meantime.
      if (!categoryTouched) categorySelect.value = guessed.category;
    } catch (_err) {
      // Guessing the category is a convenience: its failure blocks nothing.
    }
  }, 400);
}

export function closeManualForm() {
  panel.hidden = true;
  pendingImage = null;
}

function showImage(blob) {
  pendingImage = blob;
  drop.className = 'filled';
  drop.innerHTML = 'Image ready';
  const preview = document.createElement('img');
  preview.src = URL.createObjectURL(blob);
  drop.appendChild(preview);
}

async function save() {
  errorLine.textContent = '';
  const body = {
    title: document.getElementById('manual-title').value,
    description: document.getElementById('manual-description').value,
    category: categorySelect.value,
    // Empty string on purpose: the server reads it as "not rated" and removes the
    // field, which is how a difficulty set by mistake gets cleared.
    difficulty: difficultySelect.value,
    source_url: document.getElementById('manual-source').value,
  };
  const route = editing ? '/api/meta/edit' : '/api/meta';
  if (editing) body.id = editing;
  let meta;
  try {
    meta = (await postJSON(route, body)).meta;
  } catch (err) {
    errorLine.textContent = err.message;
    return;
  }
  if (pendingImage) {
    try {
      // The meta already exists — it has just been created, or it was being edited:
      // if the image upload fails we do not lose the rest, we say so and the human
      // can complete it later.
      const stored = await postBytes(`/api/meta/image?id=${meta.id}`, pendingImage);
      meta.image = stored.image;
    } catch (err) {
      const what = editing ? 'Changes saved' : 'Meta created';
      errorLine.textContent = `${what}, but image refused: ${err.message}`;
      return;
    }
  }
  closeManualForm();
  if (onDone) onDone(meta);
}

document.getElementById('manual-save').addEventListener('click', save);
document.getElementById('manual-cancel').addEventListener('click', closeManualForm);
categorySelect.addEventListener('change', () => { categoryTouched = true; });
['manual-title', 'manual-description'].forEach((id) => {
  document.getElementById(id).addEventListener('input', scheduleInference);
});

drop.addEventListener('dragover', (event) => event.preventDefault());
drop.addEventListener('drop', (event) => {
  event.preventDefault();
  const file = event.dataTransfer.files[0];
  if (file && file.type.startsWith('image/')) showImage(file);
});

document.addEventListener('paste', (event) => {
  if (!isManualFormOpen()) return;
  const item = [...(event.clipboardData?.items || [])]
    .find((candidate) => candidate.type.startsWith('image/'));
  if (!item) return;
  event.preventDefault();
  showImage(item.getAsFile());
});
