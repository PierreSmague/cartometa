import { getJSON } from './api.js';
import {
  bboxContains,
  bboxOf,
  containsPoint,
  rectangleGeometry,
  ringGeometry,
} from './geometry.js';

export class Sketch {
  constructor(map, layerGroup) {
    this.map = map;
    this.layerGroup = layerGroup;
    this.pieces = [];
    this.mode = null;

    // État de dessin en cours
    this.inProgress = null;
    this.inProgressShape = null;

    // État pour les régions admin1
    this.admin1Features = null;
    this.admin1BBoxes = null;

    // État pour la saisie au clavier
    this.currentCountry = null;
  }

  // Réinitialiser avec une liste de pièces
  reset(pieces) {
    this.pieces = pieces.slice();
    this.clear();
    this.render();
  }

  // Changer de mode de dessin
  async setMode(mode) {
    // Abandonner la pièce en cours, mais garder les pièces placées
    this.inProgress = null;
    if (this.inProgressShape) {
      this.layerGroup.removeLayer(this.inProgressShape);
      this.inProgressShape = null;
    }

    this.mode = mode;

    if (mode === 'admin1') {
      await this.ensureRegions();
    }

    this.render();
  }

  // Ajouter le polygone complet du pays courant
  async addCountry() {
    if (!this.currentCountry) {
      throw new Error('Aucun pays n\'est défini');
    }

    try {
      const data = await getJSON(`/api/country-polygon?code=${this.currentCountry}`);
      this.pieces.push({
        kind: 'country',
      });
      this.render();
    } catch (err) {
      throw new Error(`Impossible de charger le pays : ${err.message}`);
    }
  }

  // S'assurer qu'on a les données du pays (pré-chargement)
  async ensureCountry() {
    if (!this.currentCountry) {
      throw new Error('Aucun pays n\'est défini');
    }
    // Juste un test de connectivité et de disponibilité
    await getJSON(`/api/country-polygon?code=${this.currentCountry}`);
  }

  // S'assurer qu'on a les données des régions admin1
  async ensureRegions() {
    if (this.admin1Features) {
      return;
    }

    if (!this.currentCountry) {
      throw new Error('Aucun pays n\'est défini');
    }

    try {
      const data = await getJSON(`/api/admin1?code=${this.currentCountry}`);
      // data est une FeatureCollection avec des features portant code et name
      this.admin1Features = data.features || [];
      // Pré-calculer les boîtes pour le filtrage rapide au survol
      this.admin1BBoxes = this.admin1Features.map((f) => ({
        feature: f,
        bbox: bboxOf(f.geometry),
      }));
    } catch (err) {
      throw new Error(`Impossible de charger les régions : ${err.message}`);
    }
  }

  // Trouver la région admin1 au point donné (latlng)
  regionAt(latlng) {
    if (!this.admin1BBoxes) {
      return null;
    }

    const { lng, lat } = latlng;

    for (const { feature, bbox } of this.admin1BBoxes) {
      // Filtre par boîte englobante AVANT la détection de point
      // (important pour la performance : évite de ray-caster tous les points pour 10m natural earth)
      if (bboxContains(bbox, lng, lat) && containsPoint(feature.geometry, lng, lat)) {
        return feature.properties.code;
      }
    }

    return null;
  }

  // Gestionnaire de clic sur la carte
  onMapClick(latlng) {
    if (this.mode === 'rect') {
      if (!this.inProgress) {
        this.inProgress = { start: latlng };
      } else {
        // Finaliser le rectangle
        const { start } = this.inProgress;
        const west = Math.min(start.lng, latlng.lng);
        const east = Math.max(start.lng, latlng.lng);
        const south = Math.min(start.lat, latlng.lat);
        const north = Math.max(start.lat, latlng.lat);

        this.pieces.push({
          kind: 'rect',
          bounds: [west, south, east, north],
        });

        this.inProgress = null;
        if (this.inProgressShape) {
          this.layerGroup.removeLayer(this.inProgressShape);
          this.inProgressShape = null;
        }
        this.render();
      }
    } else if (this.mode === 'contour') {
      if (!this.inProgress) {
        this.inProgress = { points: [latlng] };
      } else {
        this.inProgress.points.push(latlng);
      }
      this.render();
    } else if (this.mode === 'admin1') {
      const code = this.regionAt(latlng);
      if (code) {
        this.pieces.push({
          kind: 'admin1',
          code,
        });
        this.render();
      }
    }
  }

  // Gestionnaire de mouvement de souris sur la carte
  // Retourne true si l'affichage doit être redessine
  onMapMove(latlng) {
    let shouldRender = false;

    if (this.mode === 'rect' && this.inProgress) {
      const { start } = this.inProgress;
      const west = Math.min(start.lng, latlng.lng);
      const east = Math.max(start.lng, latlng.lng);
      const south = Math.min(start.lat, latlng.lat);
      const north = Math.max(start.lat, latlng.lat);

      const bounds = [[south, west], [north, east]];
      if (!this.inProgressShape) {
        this.inProgressShape = L.rectangle(bounds, {
          color: '#ff7800',
          weight: 2,
          fill: true,
          fillColor: '#ff7800',
          fillOpacity: 0.1,
        }).addTo(this.layerGroup);
      } else {
        this.inProgressShape.setBounds(bounds);
      }
      shouldRender = true;
    } else if (this.mode === 'contour' && this.inProgress) {
      // Le contour se redessine à chaque mouvement
      shouldRender = true;
    } else if (this.mode === 'admin1') {
      // Montrer le survol d'une région
      shouldRender = true;
    }

    return shouldRender;
  }

  // Trouver la pièce la plus proche du point donné
  nearFirst(latlng) {
    let nearest = null;
    let minDist = Infinity;

    for (const piece of this.pieces) {
      const geom = this.geometryFor(piece);
      if (!geom) continue;

      // Distance approximative au centroïde de la géométrie
      let centroid = null;
      if (geom.type === 'Polygon') {
        centroid = this._centroidOfRings(geom.coordinates);
      } else if (geom.type === 'MultiPolygon') {
        centroid = this._centroidOfRings(geom.coordinates[0]);
      }

      if (centroid) {
        const dist = Math.hypot(centroid.lng - latlng.lng, centroid.lat - latlng.lat);
        if (dist < minDist) {
          minDist = dist;
          nearest = piece;
        }
      }
    }

    return nearest;
  }

  // Fermer le contour courant (passer du mode contour à un polygone placé)
  closeContour() {
    if (this.mode === 'contour' && this.inProgress && this.inProgress.points.length >= 3) {
      const ring = this.inProgress.points.map((p) => [p.lng, p.lat]);
      this.pieces.push({
        kind: 'polygon',
        ring,
      });

      this.inProgress = null;
      if (this.inProgressShape) {
        this.layerGroup.removeLayer(this.inProgressShape);
        this.inProgressShape = null;
      }
      this.render();
    }
  }

  // Annuler la dernière pièce placée
  undoLast() {
    if (this.pieces.length > 0) {
      this.pieces.pop();
      this.render();
    }
  }

  // Effacer tout (pièces et en-cours)
  clear() {
    this.pieces = [];
    this.inProgress = null;
    if (this.inProgressShape) {
      this.layerGroup.removeLayer(this.inProgressShape);
      this.inProgressShape = null;
    }
    this.render();
  }

  // Quitter le mode courant
  leaveMode() {
    this.inProgress = null;
    if (this.inProgressShape) {
      this.layerGroup.removeLayer(this.inProgressShape);
      this.inProgressShape = null;
    }
    this.mode = null;
    this.render();
  }

  // Obtenir la géométrie GeoJSON d'une pièce
  geometryFor(piece) {
    if (piece.kind === 'country') {
      // Le client ne dispose pas de la géométrie du pays ; elle est fournie par le serveur
      // Cette méthode retournera null pour les pays
      return null;
    } else if (piece.kind === 'admin1') {
      // Chercher dans les features chargées
      if (this.admin1Features) {
        const feature = this.admin1Features.find((f) => f.properties.code === piece.code);
        if (feature) {
          return feature.geometry;
        }
      }
      return null;
    } else if (piece.kind === 'rect') {
      const [west, south, east, north] = piece.bounds;
      return rectangleGeometry({ lat: south, lng: west }, { lat: north, lng: east });
    } else if (piece.kind === 'polygon') {
      return ringGeometry(piece.ring.map(([lng, lat]) => ({ lng, lat })));
    }
    return null;
  }

  // Redessiner toutes les pièces et l'en-cours
  render() {
    this.layerGroup.clearLayers();

    // Redessiner les pièces placées
    for (const piece of this.pieces) {
      this._renderPiece(piece);
    }

    // Redessiner la pièce en cours (rectangle en construction ou contour)
    if (this.mode === 'rect' && this.inProgress && !this.inProgressShape) {
      // Le rectangle en cours est géré en onMapMove
    } else if (this.mode === 'contour' && this.inProgress) {
      const points = this.inProgress.points;
      if (points.length > 0) {
        // Afficher les points du contour
        for (const point of points) {
          L.circleMarker(point, {
            radius: 4,
            color: '#0080ff',
            fillColor: '#0080ff',
            fillOpacity: 1,
            weight: 1,
          }).addTo(this.layerGroup);
        }

        // Afficher les lignes entre les points
        if (points.length > 1) {
          for (let i = 0; i < points.length - 1; i++) {
            L.polyline([points[i], points[i + 1]], {
              color: '#0080ff',
              weight: 2,
              opacity: 0.8,
            }).addTo(this.layerGroup);
          }
        }
      }
    } else if (this.mode === 'admin1') {
      // Montrer les régions disponibles au survol (cela peut être fait à la souris)
      // On peut optionnellement les préafficher en gris clair
    }
  }

  // Redessiner une pièce unique
  _renderPiece(piece) {
    const geom = this.geometryFor(piece);

    if (piece.kind === 'country') {
      // Les pays sont des pièces sans géométrie côté client
      // Afficher un marqueur ou une indication
      L.circleMarker([0, 0], {
        radius: 6,
        color: '#008000',
        fillColor: '#008000',
        fillOpacity: 1,
        weight: 2,
      })
        .bindPopup(`Pays`)
        .addTo(this.layerGroup);
    } else if (piece.kind === 'admin1') {
      if (geom) {
        L.geoJSON(geom, {
          style: {
            color: '#800080',
            weight: 2,
            opacity: 0.7,
            fillColor: '#800080',
            fillOpacity: 0.1,
          },
        }).addTo(this.layerGroup);
      }
    } else if (piece.kind === 'rect') {
      if (geom) {
        L.geoJSON(geom, {
          style: {
            color: '#ff7800',
            weight: 2,
            opacity: 0.7,
            fillColor: '#ff7800',
            fillOpacity: 0.1,
          },
        }).addTo(this.layerGroup);
      }
    } else if (piece.kind === 'polygon') {
      if (geom) {
        L.geoJSON(geom, {
          style: {
            color: '#0080ff',
            weight: 2,
            opacity: 0.7,
            fillColor: '#0080ff',
            fillOpacity: 0.1,
          },
        }).addTo(this.layerGroup);
      }
    }
  }

  // Calculer le centroïde d'un ensemble d'anneaux (polygone)
  _centroidOfRings(rings) {
    if (!rings || rings.length === 0) return null;

    const ring = rings[0]; // Aneau extérieur
    if (!ring || ring.length === 0) return null;

    let sumLng = 0;
    let sumLat = 0;
    for (const [lng, lat] of ring) {
      sumLng += lng;
      sumLat += lat;
    }
    const count = ring.length;
    return { lng: sumLng / count, lat: sumLat / count };
  }

  // Obtenir la ligne d'état (affichage du mode et du nombre de pièces)
  statusLine() {
    const modeStr = this.mode ? `Mode: ${this.mode}` : 'Mode: inactif';
    const pieceCount = this.pieces.length;
    const inProgressStr = this.inProgress ? ' (en cours)' : '';
    return `${modeStr} | Pièces: ${pieceCount}${inProgressStr}`;
  }

  // Getter pour savoir si le sketch est vide
  get isEmpty() {
    return this.pieces.length === 0 && !this.inProgress;
  }
}
