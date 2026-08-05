// Bridge between the lightbox and Anki, through AnkiConnect (an Anki add-on that
// exposes a local HTTP API). A deliberately self-contained file: app.js only publishes
// the `cartometa:loupe` event, and nothing here touches the map or the gallery. The two
// files are fingerprinted separately by the build — an import from one to the other
// would break on renaming, the event will not.

const ANKI_URL = 'http://127.0.0.1:8765';
const MODELE = 'Cartometa';
const CLE_PAQUET = 'anki-paquet';

const bouton = document.getElementById('anki-ajouter');
const etatAnki = document.getElementById('anki-etat');
const panneau = document.getElementById('anki-panneau');
const selecteur = document.getElementById('anki-paquets');
const confirmer = document.getElementById('anki-confirmer');
const guide = document.getElementById('anki-guide');

// Detail of the last `cartometa:loupe`. Every async handler keeps its own reference and
// checks on return that it is still the current one: the visitor can change meta while
// a request is in flight.
let courant = null;

async function anki(action, params = {}) {
  // No Content-Type header: the request stays "simple" in the CORS sense and spares
  // itself the preflight. AnkiConnect reads the body regardless.
  const reponse = await fetch(ANKI_URL, {
    method: 'POST',
    body: JSON.stringify({ action, version: 6, params }),
  });
  const charge = await reponse.json();
  if (charge.error) throw new Error(charge.error);
  return charge.result;
}

function cleMeta(detail) {
  // A meta's id is only unique within its country: the key published in the MetaId
  // field — and searched for duplicate detection — carries both.
  return `${detail.meta.code}-${detail.meta.id}`;
}

function reinitialiser() {
  // A meta with no image has no possible front side: no button at all, rather than a
  // button that would build an invalid card.
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
    // Searching in a note type that does not exist yet is an Anki search error, not an
    // empty result: only ask the question once the model has been created by a first
    // add.
    doublons = modeles.includes(MODELE)
      ? await anki('findNotes', { query: `"note:${MODELE}" "MetaId:${cleMeta(detail)}"` })
      : [];
  } catch (erreur) {
    // Anki closed, add-on missing, origin not allowed, network permission refused:
    // indistinguishable from here, and the answer is the same — the guide.
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
    return; // button left disabled: there is nothing more to do
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
    // Distinct from the guide: here AnkiConnect answers, it is the add itself that
    // failed (deck deleted meanwhile, image not found…). Anki's message is more useful
    // than a paraphrase.
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

// localStorage can be unavailable (private browsing, settings): remembering the last
// deck is a convenience, never a requirement.
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
    // never mind remembering it
  }
}

// --- Model and note ---------------------------------------------------------

async function assurerModele() {
  const modeles = await anki('modelNames');
  if (modeles.includes(MODELE)) return;
  // MetaId as the first field, by design: Anki requires a non-empty first field and
  // bases its duplicate check on it. The image, meanwhile, is only filled in by
  // AnkiConnect at the moment of the add.
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

// The fields of an Anki note are HTML: every text from the dataset goes through here
// before entering them. Same reason as textContent on the gallery side — the texts come
// from third-party HTML.
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
      // Optional: a hand-entered meta does not always have an original page to cite.
      Source: meta.source_url
        ? `<a href="${echapper(meta.source_url)}">Plonk It</a>`
        : '',
    },
    options: { allowDuplicate: false },
    tags: ['cartometa', meta.code],
    // `url` and not a blob: it is Anki (the desktop app) that downloads the image from
    // the site and files it in its media — it then syncs to AnkiWeb and AnkiDroid like
    // any other media.
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

// --- Mini-map ----------------------------------------------------------------

const CARTE_LARGEUR = 480;
const CARTE_HAUTEUR = 360;
const CARTE_MARGE = 20;
// Thresholds for admitting a part of the country into the framing: distance to the
// anchor, as a multiple of the anchor's extent, or area relative to the anchor's. See
// `partiesCadrantes`.
const CADRE_DISTANCE = 1.5;
const CADRE_SURFACE = 0.25;

function anneauxDe(geometrie) {
  if (!geometrie) return [];
  if (geometrie.type === 'Polygon') return [geometrie.coordinates];
  if (geometrie.type === 'MultiPolygon') return geometrie.coordinates;
  return [];
}

// Bounding box of a set of polygons. The outer ring is enough: a hole is always inside
// it.
function bboxDe(polygones) {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  for (const polygone of polygones) {
    for (const [lon, lat] of polygone[0]) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  }
  return [minLon, minLat, maxLon, maxLat];
}

// Gap between two boxes, zero if they overlap.
function ecart(a, b) {
  return Math.hypot(
    Math.max(0, a[0] - b[2], b[0] - a[2]),
    Math.max(0, a[1] - b[3], b[1] - a[3]),
  );
}

// Area of the outer ring (shoelace formula) in square degrees: enough to compare two
// parts with each other, nothing more. The bbox would not do — the nine islets of the
// Azores spread over 6° of longitude and their common box rivals mainland Portugal.
function surface(polygone) {
  const anneau = polygone[0];
  let somme = 0;
  for (let i = 0, j = anneau.length - 1; i < anneau.length; j = i++) {
    somme += anneau[j][0] * anneau[i][1] - anneau[i][0] * anneau[j][1];
  }
  return Math.abs(somme) / 2;
}

// Natural Earth gives Russia from -180° to 180°: framing on that 360° extent throws
// Chukotka to the other end of the canvas, with the country taking the other half.
// Re-expressing negative longitudes beyond 180° makes the whole thing contiguous.
// Applied to the footprint at the same time as to the silhouette, otherwise the two
// would no longer share a frame of reference.
function franchitAntimeridien(polygones) {
  const [minLon, , maxLon] = bboxDe(polygones);
  return maxLon - minLon > 180;
}

function decaler(polygones) {
  return polygones.map((polygone) => polygone.map(
    (anneau) => anneau.map(([lon, lat]) => [lon < 0 ? lon + 360 : lon, lat])));
}

// The parts of the country to frame on. A Natural Earth silhouette carries every
// territory: framing on the whole set shrinks mainland France to 1.2 % of the canvas
// (measured over the 88 published countries; Norway 1.3 % because of Bouvet Island, the
// Netherlands 0.3 % because of the Caribbean) and makes the red footprint invisible. So
// we start from the part that carries the footprint — the anchor, the one to be shown —
// and only add its close neighbours or those of comparable area: French Guiana, Bouvet
// and the Azores fall out of frame, New Guinea and Mindanao stay in. The parts left out
// are drawn all the same, simply clipped by the canvas edge.
function partiesCadrantes(parties, zone) {
  if (parties.length < 2) return parties;
  const boiteZone = zone.length ? bboxDe(zone) : null;
  // With no footprint, or on a distance tie (the case of a national footprint, which
  // touches everything), the largest part serves as the anchor.
  const ancre = parties.reduce((meilleure, partie) => {
    if (boiteZone) {
      const distanceMeilleure = ecart(bboxDe([meilleure]), boiteZone);
      const distancePartie = ecart(bboxDe([partie]), boiteZone);
      if (distancePartie !== distanceMeilleure) {
        return distancePartie < distanceMeilleure ? partie : meilleure;
      }
    }
    return surface(partie) > surface(meilleure) ? partie : meilleure;
  });
  const boiteAncre = bboxDe([ancre]);
  const etendue = Math.max(
    boiteAncre[2] - boiteAncre[0], boiteAncre[3] - boiteAncre[1],
  );
  const surfaceAncre = surface(ancre);
  return parties.filter((partie) => partie === ancre
    || ecart(bboxDe([partie]), boiteAncre) <= CADRE_DISTANCE * etendue
    || surface(partie) >= CADRE_SURFACE * surfaceAncre);
}

// The meta's footprint over the country silhouette, as base64 PNG (the format of
// AnkiConnect's `data` key). Equirectangular projection with longitude corrected by
// cos(mean latitude): the point is to place a region at a glance, not to navigate.
// Without a silhouette (country outside Natural Earth, offline build), the footprint
// frames itself; with nothing at all, null — the Anki card is then made without a
// mini-map rather than not at all.
function rendreMiniCarte(emprise, contour) {
  let pays = anneauxDe(contour);
  let zone = anneauxDe(emprise);
  if (!pays.length && !zone.length) return null;
  if (franchitAntimeridien(pays.length ? pays : zone)) {
    pays = decaler(pays);
    zone = decaler(zone);
  }
  const cadre = pays.length ? partiesCadrantes(pays, zone) : zone;
  const [minLon, minLat, maxLon, maxLat] = bboxDe(cadre);

  const latMoyenne = (minLat + maxLat) / 2;
  // A floor: at polar latitudes, cos tends to 0 and would crush everything.
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
    // evenodd: the holes (enclaves) stay holes.
    contexte.fill(cheminPays, 'evenodd');
    contexte.strokeStyle = '#9a9a94';
    contexte.lineWidth = 1;
    contexte.stroke(cheminPays);
  }
  if (zone.length) {
    const cheminZone = tracer(zone);
    // Same red as the footprint highlight on the map (see app.js and --accent in
    // style.css), for an identical meaning on both sides.
    contexte.fillStyle = 'rgba(193, 40, 58, 0.35)';
    contexte.fill(cheminZone, 'evenodd');
    contexte.strokeStyle = '#c1283a';
    contexte.lineWidth = 2;
    contexte.stroke(cheminZone);
  }
  return canvas.toDataURL('image/png').split(',')[1];
}
