// Un seul chemin pour toutes les requêtes : une erreur réseau, un code HTTP
// d'échec et un `{ok: false}` applicatif doivent tous remonter de la même
// façon, sinon l'interface avale des échecs en silence.
async function request(path, options) {
  let response;
  try {
    response = await fetch(path, options);
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

export const getJSON = (path) => request(path);

export const postJSON = (path, body) => request(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const postBytes = (path, blob) => request(path, { method: 'POST', body: blob });
