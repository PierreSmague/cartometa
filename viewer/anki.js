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

// --- Modèle et note ---------------------------------------------------------

async function assurerModele() {
  const modeles = await anki('modelNames');
  if (modeles.includes(MODELE)) return;
  // MetaId en premier champ, à dessein : Anki exige un premier champ non
  // vide et fonde dessus son contrôle de doublon. L'image, elle, n'est
  // remplie par AnkiConnect qu'au moment de l'ajout.
  await anki('createModel', {
    modelName: MODELE,
    inOrderFields: ['MetaId', 'Image', 'RegionMap', 'Explanation', 'Source'],
    css: [
      '.card { font-family: system-ui, sans-serif; font-size: 18px;',
      '  text-align: center; color: #1c1c1c; background: #fff; }',
      'img { max-width: 100%; }',
    ].join('\n'),
    cardTemplates: [{
      Name: 'Meta',
      Front: '{{Image}}',
      Back: '{{FrontSide}}<hr id="answer">{{RegionMap}}'
        + '<p>{{Explanation}}</p><p>{{Source}}</p>',
    }],
  });
}

// Les champs d'une note Anki sont du HTML : tout texte du dataset passe par
// ici avant d'y entrer. Même raison que textContent côté galerie — les
// textes viennent d'un HTML tiers.
function echapper(texte) {
  const boite = document.createElement('div');
  boite.textContent = texte ?? '';
  return boite.innerHTML;
}

function construireNote(detail, paquet) {
  const { meta, pays } = detail;
  const cle = cleMeta(detail);
  const note = {
    deckName: paquet,
    modelName: MODELE,
    fields: {
      MetaId: cle,
      Image: '',
      RegionMap: '',
      Explanation: echapper(meta.description),
      // Facultative : une méta saisie à la main n'a pas toujours de page
      // d'origine à citer.
      Source: meta.source_url
        ? `<a href="${echapper(meta.source_url)}">Plonk It</a>`
        : '',
    },
    options: { allowDuplicate: false },
    tags: ['cartometa', meta.code],
    // `url` et non un blob : c'est Anki (le logiciel de bureau) qui
    // télécharge l'image depuis le site et la range dans ses médias — elle
    // se synchronise ensuite vers AnkiWeb et AnkiDroid comme tout média.
    picture: [{
      url: detail.imageUrl,
      filename: `cartometa-${meta.code}-${detail.imageUrl.split('/').pop()}`,
      fields: ['Image'],
    }],
  };
  const carte = rendreMiniCarte(pays.geometries[meta.geom], pays.outline);
  if (carte) {
    note.picture.push({
      data: carte,
      filename: `cartometa-${cle}-map.png`,
      fields: ['RegionMap'],
    });
  }
  return note;
}

// --- Mini-carte --------------------------------------------------------------

const CARTE_LARGEUR = 480;
const CARTE_HAUTEUR = 360;
const CARTE_MARGE = 20;

function anneauxDe(geometrie) {
  if (!geometrie) return [];
  if (geometrie.type === 'Polygon') return [geometrie.coordinates];
  if (geometrie.type === 'MultiPolygon') return geometrie.coordinates;
  return [];
}

// L'emprise de la méta sur la silhouette du pays, en PNG base64 (le format
// de la clé `data` d'AnkiConnect). Projection équirectangulaire corrigée en
// longitude par cos(latitude moyenne) : il s'agit de situer une région d'un
// coup d'œil, pas de naviguer. Sans silhouette (pays hors Natural Earth,
// build hors ligne), l'emprise se cadre toute seule ; sans rien, null — la
// carte Anki se fait alors sans mini-carte plutôt que pas du tout.
function rendreMiniCarte(emprise, contour) {
  const pays = anneauxDe(contour);
  const zone = anneauxDe(emprise);
  const cadre = pays.length ? pays : zone;
  if (!cadre.length) return null;

  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  for (const polygone of cadre) {
    // L'anneau extérieur suffit au cadrage : un trou est toujours dedans.
    for (const [lon, lat] of polygone[0]) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  }

  const latMoyenne = (minLat + maxLat) / 2;
  // Plancher : aux latitudes polaires, cos tend vers 0 et écraserait tout.
  const kx = Math.max(Math.cos((latMoyenne * Math.PI) / 180), 0.05);
  const echelle = Math.min(
    (CARTE_LARGEUR - 2 * CARTE_MARGE) / (((maxLon - minLon) * kx) || 1),
    (CARTE_HAUTEUR - 2 * CARTE_MARGE) / ((maxLat - minLat) || 1),
  );
  const projeter = (lon, lat) => [
    CARTE_LARGEUR / 2 + (lon - (minLon + maxLon) / 2) * kx * echelle,
    CARTE_HAUTEUR / 2 - (lat - latMoyenne) * echelle,
  ];

  const canvas = document.createElement('canvas');
  canvas.width = CARTE_LARGEUR;
  canvas.height = CARTE_HAUTEUR;
  const contexte = canvas.getContext('2d');
  contexte.fillStyle = '#f7f7f2';
  contexte.fillRect(0, 0, CARTE_LARGEUR, CARTE_HAUTEUR);

  const tracer = (polygones) => {
    const chemin = new Path2D();
    for (const polygone of polygones) {
      for (const anneau of polygone) {
        anneau.forEach(([lon, lat], i) => {
          const [x, y] = projeter(lon, lat);
          if (i === 0) chemin.moveTo(x, y);
          else chemin.lineTo(x, y);
        });
        chemin.closePath();
      }
    }
    return chemin;
  };

  if (pays.length) {
    const cheminPays = tracer(pays);
    contexte.fillStyle = '#e4e4dc';
    // evenodd : les trous (enclaves) restent des trous.
    contexte.fill(cheminPays, 'evenodd');
    contexte.strokeStyle = '#9a9a94';
    contexte.lineWidth = 1;
    contexte.stroke(cheminPays);
  }
  if (zone.length) {
    const cheminZone = tracer(zone);
    // Même rouge que le surlignage d'emprise sur la carte (voir app.js et
    // --accent dans style.css), pour un sens identique des deux côtés.
    contexte.fillStyle = 'rgba(193, 40, 58, 0.35)';
    contexte.fill(cheminZone, 'evenodd');
    contexte.strokeStyle = '#c1283a';
    contexte.lineWidth = 2;
    contexte.stroke(cheminZone);
  }
  return canvas.toDataURL('image/png').split(',')[1];
}
