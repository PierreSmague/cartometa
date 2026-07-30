import { getJSON } from './api.js';
import {
  bboxContains, bboxOf, containsPoint, rectangleGeometry, ringGeometry,
} from './geometry.js';

const POSE = { color: '#0a7d2b', weight: 2, fillOpacity: 0.25 };
const EN_COURS = { color: '#0a7d2b', weight: 2, dashArray: '5 5', fill: false };
const SURVOL = { color: '#0057d9', weight: 2, fillOpacity: 0.15 };

// Rayon d'accrochage au premier sommet, en pixels écran : c'est le geste qui
// ferme un contour libre.
const FERMETURE_PX = 12;

const NOMS = { rect: 'rectangle', contour: 'contour libre', admin1: 'subdivisions' };

export class Sketch {
  constructor(map, layerGroup) {
    this.map = map;
    this.layers = layerGroup;
    this.pieces = [];
    this.mode = null;
    this.corner = null;     // premier coin d'un rectangle en cours
    this.vertices = [];     // sommets d'un contour en cours
    this.preview = null;    // géométrie élastique suivant le curseur
    this.hovered = null;    // code de la région survolée en mode admin1
    this.country = null;    // silhouette du pays, chargée une fois
    this.regions = null;    // index des régions admin-1, chargé une fois
  }

  get isEmpty() {
    return this.pieces.length === 0;
  }

  reset(pieces) {
    this.pieces = pieces ? pieces.map((piece) => ({ ...piece })) : [];
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
    // Changer de mode abandonne le morceau en cours mais garde les posés :
    // c'est le cumul qui est la règle, pas la substitution.
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
    // Une région admin-1 au 1:10m peut compter des dizaines de milliers de
    // sommets. Sans ce filtre par boîte englobante, chaque mouvement de
    // souris relancerait un lancer de rayon sur toutes les régions du pays.
    this.regions = collection.features.map((feature) => ({
      code: feature.properties.code,
      name: feature.properties.name,
      geometry: feature.geometry,
      bbox: bboxOf(feature.geometry),
    }));
    return this.regions;
  }

  async ensurePiecesGeometry() {
    // Une méta rouverte (--all) arrive avec des morceaux qui référencent une
    // géométrie distante : la silhouette du pays et/ou les régions admin-1
    // ne sont chargées ici que si un morceau déjà posé en a besoin — sans
    // attendre que l'utilisateur presse P ou S, sans quoi ces morceaux
    // resteraient invisibles (et ⌫ retirerait un morceau que rien n'affiche).
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
    // Contextuel : tant qu'un contour est ouvert, ⌫ défait le dernier
    // sommet. C'est le geste attendu, et sinon un contour raté ne se
    // corrigerait qu'en le recommençant entièrement.
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
      return { type: 'Polygon', coordinates: [[...piece.ring, piece.ring[0]]] };
    }
    if (piece.kind === 'country') return this.country;
    const region = (this.regions || []).find((r) => r.code === piece.code);
    return region ? region.geometry : null;
  }

  render() {
    this.pieces.forEach((piece) => {
      const geometry = this.geometryFor(piece);
      if (geometry) L.geoJSON(geometry, POSE).addTo(this.layers);
    });
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
        parts.push(this.corner ? 'clique le coin opposé' : 'clique le premier coin');
      }
      if (this.mode === 'contour') {
        parts.push(this.vertices.length >= 3
          ? 'reclique le premier sommet pour fermer (ou Entrée)'
          : `${this.vertices.length}/3 sommets`);
      }
      if (this.mode === 'admin1') {
        const region = this.regions && this.hovered
          ? this.regions.find((r) => r.code === this.hovered)
          : null;
        parts.push(region ? region.name : 'survole une région');
      }
    }
    if (this.pieces.length) {
      parts.push(`${this.pieces.length} morceau${this.pieces.length > 1 ? 'x' : ''}`);
      parts.push('A enregistrer · ⌫ retirer · 0 vider');
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