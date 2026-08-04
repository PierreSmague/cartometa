// Pont entre la loupe et Anki, via AnkiConnect (module Anki qui expose une
// API HTTP locale). Fichier délibérément autonome : app.js ne publie que
// l'événement `cartometa:loupe`, et rien ici ne touche à la carte ni à la
// galerie. Les deux fichiers sont empreintés séparément par le build — un
// import de l'un vers l'autre casserait au renommage, l'événement non.

const ANKI_URL = 'http://127.0.0.1:8765';
const MODELE = 'Cartometa';
const CLE_PAQUET = 'anki-paquet';

const bouton = document.getElementById('anki-ajouter');
const etatAnki = document.getElementById('anki-etat');
const panneau = document.getElementById('anki-panneau');
const selecteur = document.getElementById('anki-paquets');
const confirmer = document.getElementById('anki-confirmer');
const guide = document.getElementById('anki-guide');

// Détail du dernier `cartometa:loupe`. Chaque gestionnaire asynchrone en
// garde sa propre référence et vérifie au retour qu'elle est toujours la
// courante : le visiteur peut changer de méta pendant qu'une requête vole.
let courant = null;

async function anki(action, params = {}) {
  // Pas d'en-tête Content-Type : la requête reste « simple » au sens CORS et
  // s'épargne le préversement. AnkiConnect lit le corps quoi qu'il en soit.
  const reponse = await fetch(ANKI_URL, {
    method: 'POST',
    body: JSON.stringify({ action, version: 6, params }),
  });
  const charge = await reponse.json();
  if (charge.error) throw new Error(charge.error);
  return charge.result;
}

function cleMeta(detail) {
  // L'id d'une méta n'est unique que dans son pays : la clé publiée dans le
  // champ MetaId — et cherchée pour la détection de doublon — porte les deux.
  return `${detail.meta.code}-${detail.meta.id}`;
}

function reinitialiser() {
  // La méta sans image n'a pas de recto possible : pas de bouton du tout,
  // plutôt qu'un bouton qui fabriquerait une carte invalide.
  bouton.hidden = !courant?.imageUrl;
  bouton.disabled = false;
  bouton.textContent = 'Add to Anki';
  etatAnki.textContent = '';
  panneau.hidden = true;
  guide.hidden = true;
  guide.open = false;
}

document.addEventListener('cartometa:loupe', (evenement) => {
  courant = evenement.detail;
  reinitialiser();
});

document.addEventListener('cartometa:loupe-fermee', () => {
  courant = null;
});

bouton.addEventListener('click', async () => {
  const detail = courant;
  bouton.disabled = true;
  etatAnki.textContent = '…';
  let paquets;
  let doublons;
  try {
    const [noms, modeles] = await Promise.all([
      anki('deckNames'),
      anki('modelNames'),
    ]);
    paquets = noms;
    // Chercher dans un type de note qui n'existe pas encore est une erreur
    // de recherche Anki, pas un résultat vide : ne poser la question qu'une
    // fois le modèle créé par un premier ajout.
    doublons = modeles.includes(MODELE)
      ? await anki('findNotes', { query: `"note:${MODELE}" "MetaId:${cleMeta(detail)}"` })
      : [];
  } catch (erreur) {
    // Anki fermé, module absent, origine non autorisée, permission réseau
    // refusée : indistinguables d'ici, et la réponse est la même — le guide.
    if (courant !== detail) return;
    etatAnki.textContent = "Anki isn't responding.";
    guide.hidden = false;
    bouton.disabled = false;
    return;
  }
  if (courant !== detail) return;
  etatAnki.textContent = '';
  if (doublons.length) {
    bouton.textContent = 'Already in Anki';
    return; // bouton laissé désactivé : il n'y a rien de plus à faire
  }
  const options = [...paquets].sort().map((nom) => new Option(nom, nom));
  selecteur.replaceChildren(...options);
  const memorise = lirePaquetMemorise();
  if (memorise && paquets.includes(memorise)) selecteur.value = memorise;
  panneau.hidden = false;
});

confirmer.addEventListener('click', async () => {
  const detail = courant;
  const paquet = selecteur.value;
  confirmer.disabled = true;
  etatAnki.textContent = 'Adding…';
  try {
    await assurerModele();
    await anki('addNote', { note: construireNote(detail, paquet) });
  } catch (erreur) {
    if (courant !== detail) return;
    confirmer.disabled = false;
    // Distinct du guide : ici AnkiConnect répond, c'est l'ajout lui-même qui
    // a échoué (paquet supprimé entre-temps, image introuvable…). Le message
    // d'Anki est plus utile qu'une paraphrase.
    etatAnki.textContent = `Could not add the card: ${erreur.message}`;
    return;
  }
  if (courant !== detail) return;
  memoriserPaquet(paquet);
  confirmer.disabled = false;
  panneau.hidden = true;
  etatAnki.textContent = '';
  bouton.textContent = '✓ Added';
});

// localStorage peut être indisponible (navigation privée, réglages) : le
// souvenir du dernier paquet est un confort, jamais une condition.
function lirePaquetMemorise() {
  try {
    return localStorage.getItem(CLE_PAQUET);
  } catch {
    return null;
  }
}

function memoriserPaquet(paquet) {
  try {
    localStorage.setItem(CLE_PAQUET, paquet);
  } catch {
    // tant pis pour le souvenir
  }
}

// --- Provisoire : remplacé par la tâche 6 ----------------------------------

async function assurerModele() {
  throw new Error('pas encore implémenté');
}

function construireNote(detail, paquet) {
  throw new Error('pas encore implémenté');
}
