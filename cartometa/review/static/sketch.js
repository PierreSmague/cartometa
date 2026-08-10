import { getJSON, postJSON } from './api.js';
import {
  bboxContains, bboxOf, containsPoint, rectangleGeometry, ringGeometry,
} from './geometry.js';

const POSE = { color: '#0a7d2b', weight: 2, fillOpacity: 0.25 };
const EN_COURS = { color: '#0a7d2b', weight: 2, dashArray: '5 5', fill: false };
const SURVOL = { color: '#0057d9', weight: 2, fillOpacity: 0.15 };

// Snapping radius to the first vertex, in screen pixels: this is the gesture that
// closes a freehand outline.
const FERMETURE_PX = 12;

const NOMS = { rect: 'rectangle', contour: 'freehand outline', admin1: 'subdivisions' };

export class Sketch {
  constructor(map, layerGroup) {
    this.map = map;
    this.layers = layerGroup;
    this.pieces = [];
    this.mode = null;
    this.corner = null;     // first corner of a rectangle in progress
    this.vertices = [];     // vertices of an outline in progress
    this.preview = null;    // rubber-band geometry following the cursor
    this.hovered = null;    // code of the region hovered in admin1 mode
    this.country = null;    // country silhouette, loaded once
    this.regions = null;    // index of the admin-1 regions, loaded once
    this.clipped = null;    // clipped union returned by the server
    this.clippedKey = null; // the pieces that produced `clipped`
  }

  // Clipping is a modifier, not a surface: it does not count towards the pieces,
  // and an area that holds nothing but clipping is empty.
  get operands() {
    return this.pieces.filter((piece) => piece.kind !== 'clip');
  }

  get clipping() {
    return this.pieces.some((piece) => piece.kind === 'clip');
  }

  get isEmpty() {
    return this.operands.length === 0;
  }

  reset(pieces) {
    this.pieces = pieces ? pieces.map((piece) => ({ ...piece })) : [];
    this.clipped = null;
    this.clippedKey = null;
    this.leaveMode();
  }

  leaveMode() {
    this.mode = null;
    this.corner = null;
    this.vertices = [];
    this.preview = null;
    this.hovered = null;
  }

  clear() {
    this.pieces = [];
    this.leaveMode();
  }

  async setMode(mode) {
    // Switching mode abandons the piece in progress but keeps the ones laid down:
    // accumulation is the rule, not substitution.
    this.leaveMode();
    if (mode === 'admin1') await this.ensureRegions();
    this.mode = mode;
  }

  async ensureCountry() {
    if (!this.country) this.country = (await getJSON('/api/country-polygon')).geometry;
    return this.country;
  }

  async ensureRegions() {
    if (this.regions) return this.regions;
    const collection = await getJSON('/api/admin1');
    // An admin-1 region at 1:10m can have tens of thousands of vertices. Without
    // this bounding-box filter, every mouse move would rerun a ray cast over every
    // region of the country.
    this.regions = collection.features.map((feature) => ({
      code: feature.properties.code,
      name: feature.properties.name,
      geometry: feature.geometry,
      bbox: bboxOf(feature.geometry),
    }));
    return this.regions;
  }

  async ensurePiecesGeometry() {
    // A reopened meta (--all) arrives with pieces that reference remote geometry:
    // the country silhouette and/or the admin-1 regions are only loaded here if a
    // piece already laid down needs them — without waiting for the user to press P
    // or S, otherwise those pieces would stay invisible (and ⌫ would remove a piece
    // nothing displays).
    const tasks = [];
    if (this.pieces.some((piece) => piece.kind === 'country')) tasks.push(this.ensureCountry());
    if (this.pieces.some((piece) => piece.kind === 'admin1')) tasks.push(this.ensureRegions());
    if (tasks.length) await Promise.all(tasks);
  }

  async addCountry() {
    await this.ensureCountry();
    this.leaveMode();
    if (!this.pieces.some((piece) => piece.kind === 'country')) {
      this.pieces.push({ kind: 'country' });
    }
  }

  toggleClip() {
    const at = this.pieces.findIndex((piece) => piece.kind === 'clip');
    if (at >= 0) this.pieces.splice(at, 1);
    else this.pieces.push({ kind: 'clip' });
  }

  // Signature of the pieces the clipped preview depends on, or null when there is
  // nothing to clip.
  clipKey() {
    if (!this.clipping || !this.operands.length) return null;
    return JSON.stringify(this.pieces);
  }

  needsClip() {
    return this.clipKey() !== this.clippedKey;
  }

  // True only when the clipped preview matches the CURRENT pieces: a piece laid
  // down during the round trip makes the preview stale, and showing the old one
  // would display an area without the piece that was just added.
  get clipReady() {
    return this.clipping && this.clipped !== null && !this.needsClip();
  }

  async ensureClip() {
    const key = this.clipKey();
    if (key === this.clippedKey) return;
    // Mark the attempt BEFORE the call: if the server refuses (area entirely
    // outside the country), needsClip() falls back to false and the rendering
    // returns to the raw pieces instead of asking again endlessly.
    this.clippedKey = key;
    this.clipped = null;
    if (!key) return;
    const { geometry } = await postJSON('/api/resolve', { pieces: this.pieces });
    // The pieces may have moved while we waited: a stale preview must not be
    // displayed. The next draw() will restart the resolution.
    if (this.clipKey() !== key) return;
    this.clipped = geometry;
  }

  regionAt(latlng) {
    if (!this.regions) return null;
    return this.regions.find(
      (region) => bboxContains(region.bbox, latlng.lng, latlng.lat)
        && containsPoint(region.geometry, latlng.lng, latlng.lat),
    ) || null;
  }

  onMapClick(latlng) {
    if (this.mode === 'rect') {
      if (!this.corner) {
        this.corner = latlng;
        this.preview = null;
      } else {
        this.pieces.push({ kind: 'rect', bounds: boundsOf(this.corner, latlng) });
        this.corner = null;
        this.preview = null;
      }
      return;
    }
    if (this.mode === 'contour') {
      if (this.vertices.length >= 3 && this.nearFirst(latlng)) {
        this.closeContour();
        return;
      }
      this.vertices.push(latlng);
      this.preview = null;
      return;
    }
    if (this.mode === 'admin1') {
      const region = this.regionAt(latlng);
      if (!region) return;
      const already = this.pieces.findIndex(
        (piece) => piece.kind === 'admin1' && piece.code === region.code,
      );
      if (already >= 0) this.pieces.splice(already, 1);
      else this.pieces.push({ kind: 'admin1', code: region.code });
    }
  }

  onMapMove(latlng) {
    if (this.mode === 'rect' && this.corner) {
      this.preview = rectangleGeometry(this.corner, latlng);
      return true;
    }
    if (this.mode === 'contour' && this.vertices.length) {
      this.preview = ringGeometry([...this.vertices, latlng]);
      return true;
    }
    if (this.mode === 'admin1') {
      const region = this.regionAt(latlng);
      const code = region ? region.code : null;
      if (code === this.hovered) return false;
      this.hovered = code;
      return true;
    }
    return false;
  }

  nearFirst(latlng) {
    const first = this.map.latLngToContainerPoint(this.vertices[0]);
    return first.distanceTo(this.map.latLngToContainerPoint(latlng)) <= FERMETURE_PX;
  }

  closeContour() {
    if (this.vertices.length < 3) return;
    this.pieces.push({
      kind: 'polygon',
      ring: this.vertices.map((p) => [p.lng, p.lat]),
    });
    this.vertices = [];
    this.preview = null;
  }

  undoLast() {
    // Contextual: while an outline is open, ⌫ undoes the last vertex. That is the
    // expected gesture, and otherwise a botched outline could only be fixed by
    // starting it over entirely.
    if (this.mode === 'contour' && this.vertices.length) {
      this.vertices.pop();
      this.preview = null;
      return;
    }
    if (this.mode === 'rect' && this.corner) {
      this.corner = null;
      this.preview = null;
      return;
    }
    this.pieces.pop();
  }

  geometryFor(piece) {
    if (piece.kind === 'rect') {
      const [west, south, east, north] = piece.bounds;
      return {
        type: 'Polygon',
        coordinates: [[
          [west, south], [east, south], [east, north], [west, north], [west, south],
        ]],
      };
    }
    if (piece.kind === 'polygon') {
      // Les trous n'existent que sur les pièces importées (corridors) : le
      // dessin à la souris n'en produit jamais.
      const close = (ring) => [...ring, ring[0]];
      return {
        type: 'Polygon',
        coordinates: [close(piece.ring), ...(piece.holes || []).map(close)],
      };
    }
    if (piece.kind === 'country') return this.country;
    const region = (this.regions || []).find((r) => r.code === piece.code);
    return region ? region.geometry : null;
  }

  render() {
    if (this.clipReady) {
      // Clipped area: what is displayed is the union clipped by the server, not the
      // raw pieces — what you see is exactly what `A` would save. Until it arrives
      // (or if the server refused it), we fall back to the raw pieces below.
      L.geoJSON(this.clipped, POSE).addTo(this.layers);
    } else {
      this.operands.forEach((piece) => {
        const geometry = this.geometryFor(piece);
        if (geometry) L.geoJSON(geometry, POSE).addTo(this.layers);
      });
    }
    if (this.mode === 'admin1' && this.hovered) {
      const region = this.regions.find((r) => r.code === this.hovered);
      const posee = this.pieces.some((p) => p.kind === 'admin1' && p.code === this.hovered);
      if (region && !posee) L.geoJSON(region.geometry, SURVOL).addTo(this.layers);
    }
    if (this.preview) L.geoJSON(this.preview, EN_COURS).addTo(this.layers);
    this.vertices.forEach((vertex, position) => {
      L.circleMarker(vertex, {
        radius: position === 0 ? 6 : 4, color: '#0a7d2b', fillOpacity: 1,
      }).addTo(this.layers);
    });
    if (this.corner) {
      L.circleMarker(this.corner, {
        radius: 4, color: '#0a7d2b', fillOpacity: 1,
      }).addTo(this.layers);
    }
  }

  statusLine() {
    const parts = [];
    if (this.mode) {
      parts.push(`mode ${NOMS[this.mode]}`);
      if (this.mode === 'rect') {
        parts.push(this.corner ? 'click the opposite corner' : 'click the first corner');
      }
      if (this.mode === 'contour') {
        parts.push(this.vertices.length >= 3
          ? 'click the first vertex again to close (or press Enter)'
          : `${this.vertices.length}/3 vertices`);
      }
      if (this.mode === 'admin1') {
        const region = this.regions && this.hovered
          ? this.regions.find((r) => r.code === this.hovered)
          : null;
        parts.push(region ? region.name : 'hover a region');
      }
    }
    const poses = this.operands.length;
    if (poses) {
      parts.push(`${poses} piece${poses > 1 ? 's' : ''}`);
      if (this.clipping) {
        if (this.clipReady) parts.push('clipped to the borders');
        else if (this.needsClip()) parts.push('clipping…');
        // Attempt made and fruitless: the error banner says why.
        else parts.push('clipping impossible');
      }
      parts.push('A save · ⌫ remove · 0 empty');
    } else if (this.clipping) {
      parts.push('clipping armed - lay down a piece (F to cancel)');
    }
    return parts.join(' — ');
  }
}

function boundsOf(a, b) {
  return [
    Math.min(a.lng, b.lng), Math.min(a.lat, b.lat),
    Math.max(a.lng, b.lng), Math.max(a.lat, b.lat),
  ];
}