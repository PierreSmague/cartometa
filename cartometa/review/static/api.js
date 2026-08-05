// A single path for every request: a network error, a failing HTTP status and an
// application-level `{ok: false}` must all surface the same way, otherwise the
// interface swallows failures silently.
async function request(path, options) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (err) {
    throw new Error(`lost connection to the server: ${err.message}`);
  }
  let data = {};
  try {
    data = await response.json();
  } catch (_err) {
    // no usable JSON body: we fall back to the HTTP status
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `HTTP error ${response.status}`);
  }
  return data;
}

export const getJSON = (path) => request(path);

export const postJSON = (path, body) => request(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const postBytes = (path, blob) => request(path, { method: 'POST', body: blob });
