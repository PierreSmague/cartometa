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

// Ray casting. A point on a border may fall on one side or the other depending on
// rounding: of no consequence here, the human just clicks again.
//
// The `j = i, i += 1` update makes `j` the PREVIOUS vertex: it is the (i, j) pair
// that describes the edge. Writing it `j = i += 1` would give `j` the incremented
// value and test zero-length edges.
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
  // Outside the outer ring, or inside a hole: either way, outside.
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
