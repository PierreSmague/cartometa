export function rectangleGeometry(a, b) {
  const [west, east] = [Math.min(a.lng, b.lng), Math.max(a.lng, b.lng)];
  const [south, north] = [Math.min(a.lat, b.lat), Math.max(a.lat, b.lat)];
  return {
    type: 'Polygon',
    coordinates: [[
      [west, south], [east, south], [east, north], [west, north], [west, south],
    ]],
  };
}

export function ringGeometry(points) {
  const ring = points.map((p) => [p.lng, p.lat]);
  return { type: 'Polygon', coordinates: [[...ring, ring[0]]] };
}

export function bboxOf(geometry) {
  let west = 180;
  let south = 90;
  let east = -180;
  let north = -90;
  const scan = (coords) => {
    if (typeof coords[0] === 'number') {
      west = Math.min(west, coords[0]);
      east = Math.max(east, coords[0]);
      south = Math.min(south, coords[1]);
      north = Math.max(north, coords[1]);
    } else {
      coords.forEach(scan);
    }
  };
  scan(geometry.coordinates);
  return [west, south, east, north];
}

export function bboxContains(bbox, x, y) {
  return x >= bbox[0] && x <= bbox[2] && y >= bbox[1] && y <= bbox[3];
}

// Lancer de rayon. Un point sur une frontière peut tomber d'un côté ou de
// l'autre selon l'arrondi : sans conséquence ici, l'humain reclique.
//
// La mise à jour `j = i, i += 1` fait de `j` le sommet PRÉCÉDENT : c'est la
// paire (i, j) qui décrit l'arête. L'écrire `j = i += 1` donnerait à `j` la
// valeur incrémentée et testerait des arêtes de longueur nulle.
function ringContains(ring, x, y) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const straddles = (yi > y) !== (yj > y);
    if (straddles && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function polygonContains(rings, x, y) {
  // Hors de l'anneau extérieur, ou dans un trou : dans les deux cas, dehors.
  if (!ringContains(rings[0], x, y)) return false;
  return !rings.slice(1).some((hole) => ringContains(hole, x, y));
}

export function containsPoint(geometry, x, y) {
  if (geometry.type === 'Polygon') return polygonContains(geometry.coordinates, x, y);
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates.some((rings) => polygonContains(rings, x, y));
  }
  return false;
}
