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
  // Un SUCCÈS seul est mis en cache : la cible d'un lien court ne change pas.
  // Un échec, jamais — et c'est un défaut vécu, pas une précaution théorique.
  // La chaîne de redirections de Google passe par une page de consentement et
  // n'aboutit pas toujours ; mettre ce résultat en cache 24 h gravait un échec
  // passager dans le navigateur du visiteur, qui voyait ensuite le même lien
  // échouer indéfiniment alors qu'il se résolvait très bien par ailleurs.
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

// Nombre de sauts suivis à la main. La chaîne observée en fait trois
// (lien court → Maps → consentement → Maps) ; cinq laisse de la marge sans
// permettre une boucle infinie.
const SAUTS_MAX = 5;

// Suit la chaîne de redirections en inspectant CHAQUE en-tête `Location`,
// plutôt que la seule URL finale.
//
// C'est ce qui rend la résolution fiable : les coordonnées sont présentes dès
// la PREMIÈRE redirection, alors que la fin de la chaîne passe par
// `consent.google.com` et n'aboutit pas toujours. Ne lire que l'URL finale
// faisait donc échouer par intermittence des liens parfaitement valides.
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
    // Le corps ne sert jamais : seules les adresses portent le point.
    reponse.body?.cancel();
    const suite = reponse.headers.get('location');
    if (!suite) break;
    // `new URL(suite, courante)` : un `Location` peut être relatif.
    courante = new URL(suite, courante).toString();
    const point = extraire(courante);
    if (point) return point;
  }

  // Repli : si aucune redirection n'a livré le point, on laisse le runtime
  // suivre la chaîne entière et on lit l'URL d'arrivée. C'est la méthode du
  // résolveur Python, éprouvée sur 2007 liens.
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

  // `latlon: null` avec un 200 : le lien a bien été suivi, il ne portait
  // simplement pas de coordonnées. Ce n'est pas une panne — et le front
  // distingue ce cas d'un échec de transport, qui a son propre message.
  return json({ latlon: point });
}
