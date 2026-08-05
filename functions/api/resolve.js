// Minimal relay: follows a shortened Google Maps link's redirect and returns its
// coordinates.
//
// Why a server endpoint when the whole rest of the site is static: `goo.gl` sends
// no CORS header (verified), so the browser refuses to expose the redirect to the
// page. That is a browser rule, not a detail that can be worked around client-side.
//
// Server-side counterpart of `cartometa/extract/maps_links.py`: same patterns, same
// method (follow the redirects then read the final URL). That resolver resolved
// 2007 real links without a single failure — we reproduce what works rather than
// invent a variant.

// Strict allowlist. Without it, this endpoint would be a relay able to probe any
// server from our origin, internal addresses included. The only two hosts Google
// Maps produces when sharing.
const HOTES_AUTORISES = new Set(['maps.app.goo.gl', 'goo.gl']);

// Taken from `LATLON_RE` and `VIEWPOINT_RE` on the build side, plus the place card.
const MOTIFS = [
  /\/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,
  /[?&]viewpoint=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,
  /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/,
];

const USER_AGENT = 'cartometa/1.0 (+https://cartometa.com)';

function json(charge, statut = 200) {
  // Only a SUCCESS is cached: a short link's target does not change. A failure,
  // never — and that is a defect lived through, not a theoretical precaution.
  // Google's redirect chain goes through a consent page and does not always get to
  // the end; caching that result for 24 h engraved a transient failure into the
  // visitor's browser, who then saw the same link fail indefinitely while it
  // resolved perfectly well elsewhere.
  const reussite = Array.isArray(charge.latlon);
  return new Response(JSON.stringify(charge), {
    status: statut,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': reussite ? 'public, max-age=86400' : 'no-store',
    },
  });
}

function extraire(url) {
  for (const motif of MOTIFS) {
    const trouve = url.match(motif);
    if (!trouve) continue;
    const lat = Number(trouve[1]);
    const lon = Number(trouve[2]);
    // A pattern can match something other than a point: out of bounds, we refuse
    // rather than return an absurd position.
    if (
      Number.isFinite(lat) && Number.isFinite(lon)
      && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
    ) {
      return [lat, lon];
    }
  }
  return null;
}

// Number of hops followed by hand. The observed chain has three (short link → Maps
// → consent → Maps); five leaves margin without allowing an infinite loop.
const SAUTS_MAX = 5;

// Follows the redirect chain by inspecting EVERY `Location` header, rather than only
// the final URL.
//
// That is what makes the resolution reliable: the coordinates are present from the
// FIRST redirect onwards, whereas the end of the chain goes through
// `consent.google.com` and does not always get there. Reading only the final URL
// therefore made perfectly valid links fail intermittently.
async function suivreEtExtraire(depart) {
  let courante = depart;
  for (let saut = 0; saut < SAUTS_MAX; saut += 1) {
    let reponse;
    try {
      reponse = await fetch(courante, {
        redirect: 'manual',
        headers: { 'User-Agent': USER_AGENT },
      });
    } catch {
      break;
    }
    // The body is never of any use: only the addresses carry the point.
    reponse.body?.cancel();
    const suite = reponse.headers.get('location');
    if (!suite) break;
    // `new URL(suite, courante)`: a `Location` can be relative.
    courante = new URL(suite, courante).toString();
    const point = extraire(courante);
    if (point) return point;
  }

  // Fallback: if no redirect delivered the point, we let the runtime follow the
  // whole chain and read the arrival URL. That is the Python resolver's method,
  // proven over 2007 links.
  try {
    const reponse = await fetch(depart, {
      redirect: 'follow',
      headers: { 'User-Agent': USER_AGENT },
    });
    const finale = reponse.url;
    reponse.body?.cancel();
    return extraire(finale || '');
  } catch {
    return null;
  }
}

export async function onRequestGet({ request }) {
  const brut = new URL(request.url).searchParams.get('url');
  if (!brut) return json({ error: 'missing url' }, 400);

  let cible;
  try {
    cible = new URL(brut);
  } catch {
    return json({ error: 'invalid url' }, 400);
  }
  if (cible.protocol !== 'https:' || !HOTES_AUTORISES.has(cible.hostname)) {
    return json({ error: 'host not allowed' }, 400);
  }

  const point = await suivreEtExtraire(cible.toString());

  // `latlon: null` with a 200: the link was indeed followed, it simply carried no
  // coordinates. That is not a failure — and the front end tells this case apart
  // from a transport failure, which has its own message.
  return json({ latlon: point });
}
