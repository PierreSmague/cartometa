import { getJSON, postBytes, postJSON } from './api.js';

const panel = document.getElementById('manual');
const drop = document.getElementById('drop');
const errorLine = document.getElementById('manual-error');
const categorySelect = document.getElementById('manual-category');

let pendingImage = null;   // Pending blob, sent once the meta has been created
let onCreated = null;
// As soon as the human has picked a category, inference goes quiet: suggesting is
// useful, overwriting an explicit choice never is.
let categoryTouched = false;
let inferTimer = null;

export function isManualFormOpen() {
  return !panel.hidden;
}

export function openManualForm(callback) {
  onCreated = callback;
  pendingImage = null;
  categoryTouched = false;
  errorLine.textContent = '';
  drop.className = '';
  drop.innerHTML = 'Drop an image here, or paste it with Ctrl+V';
  ['manual-title', 'manual-description', 'manual-source'].forEach((id) => {
    document.getElementById(id).value = '';
  });
  categorySelect.value = 'autre';
  panel.hidden = false;
  document.getElementById('manual-title').focus();
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
    source_url: document.getElementById('manual-source').value,
  };
  let meta;
  try {
    meta = (await postJSON('/api/meta', body)).meta;
  } catch (err) {
    errorLine.textContent = err.message;
    return;
  }
  if (pendingImage) {
    try {
      // The meta already exists: if the image upload fails we do not lose it, we
      // say so and the human can complete it later.
      const stored = await postBytes(`/api/meta/image?id=${meta.id}`, pendingImage);
      meta.image = stored.image;
    } catch (err) {
      errorLine.textContent = `Meta created, but image refused: ${err.message}`;
      return;
    }
  }
  closeManualForm();
  if (onCreated) onCreated(meta);
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
