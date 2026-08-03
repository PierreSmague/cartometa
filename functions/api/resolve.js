// Relais minimal : suit la redirection d'un lien Google Maps raccourci et
// renvoie ses coordonnées.
//
// Pourquoi un point d'appel serveur alors que tout le reste du site est
// statique : `goo.gl` n'envoie aucun en-tête CORS (vérifié), donc le
// navigateur refuse d'exposer la redirection à la page. C'est une règle du
// navigateur, pas un détail contournable côté client.
//
// Pendant serveur de `cartometa/extract/maps_links.py` : mêmes motifs, même
// méthode (suivre les redirections puis lire l'URL finale). Ce résolveur-là a
// résolu 2007 liens réels sans un seul échec — on reproduit ce qui marche
// plutôt que d'inventer une variante.

// Liste blanche stricte. Sans elle, ce point d'appel serait un relais capable
// de sonder n'importe quel serveur depuis notre origine, adresses internes
// comprises. Les deux seuls hôtes que Google Maps produit au partage.
const HOTES_AUTORISES = new Set(['maps.app.goo.gl', 'goo.gl']);

// Repris de `LATLON_RE` et `VIEWPOINT_RE` côté build, plus la fiche de lieu.
const MOTIFS = [
  /\/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,
  /[?&]viewpoint=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/,
  /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/,
];

const USER_AGENT = 'cartometa/1.0 (+https://cartometa.com)';

function json(charge, statut = 200) {
  return new Response(JSON.stringify(charge), {
    status: statut,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      // La cible d'un lien court ne change pas : une résolution reste valable.
      'Cache-Control': 'public, max-age=86400',
    },
  });
}

function extraire(url) {
  for (const motif of MOTIFS) {
    const trouve = url.match(motif);
    if (!trouve) continue;
    const lat = Number(trouve[1]);
    const lon = Number(trouve[2]);
    // Un motif peut coïncider avec autre chose qu'un point : hors bornes, on
    // refuse plutôt que de renvoyer une position absurde.
    if (
      Number.isFinite(lat) && Number.isFinite(lon)
      && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
    ) {
      return [lat, lon];
    }
  }
  return null;
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

  let finale;
  try {
    const reponse = await fetch(cible.toString(), {
      redirect: 'follow',
      headers: { 'User-Agent': USER_AGENT },
    });
    finale = reponse.url;
    // Le corps ne sert à rien — seule l'URL finale compte. L'annuler évite de
    // rapatrier une page Google Maps entière à chaque résolution.
    reponse.body?.cancel();
  } catch {
    return json({ error: 'upstream failed' }, 502);
  }

  // `latlon: null` avec un 200 : le lien est valide et a bien été suivi, il
  // ne portait simplement pas de coordonnées. Ce n'est pas une panne, et le
  // front le distingue déjà d'un échec réseau.
  return json({ latlon: extraire(finale || '') });
}
