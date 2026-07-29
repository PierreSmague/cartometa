from __future__ import annotations

import argparse
import json
import math
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from shapely.affinity import translate
from shapely.geometry import Point, mapping, shape

from cartometa.atomic_write import write_json_atomic

STATIC = Path(__file__).resolve().parent / "static"
STATE = {"data": Path("data"), "country": "PL"}


def _paths() -> tuple[Path, Path]:
    data, country = STATE["data"], STATE["country"]
    return data / "metas" / f"{country}.json", data / "geo" / f"{country}.geojson"


def _write_atomic(path: Path, payload: dict) -> None:
    write_json_atomic(path, payload)


class UnknownMetaError(ValueError):
    """Levée quand un `id` ne correspond à aucune méta connue."""


# Nom de la propriété où l'on sauvegarde la géométrie écrasée par une
# correction de rayon, pour pouvoir la restaurer si l'humain annule (touche U).
_GEOMETRY_BACKUP_KEY = "geometry_before_correction"

# Un décalage au clavier sert à recaler une zone de quelques dizaines de
# kilomètres, pas à la déplacer sur un autre continent. Au-delà, c'est une
# erreur de saisie ou un client incorrect : on refuse plutôt que d'écrire.
MAX_OFFSET_DEG = 5.0


def _validate_offset(offset: object) -> tuple[float, float]:
    """Contrôle le décalage reçu et le renvoie en (Δlongitude, Δlatitude).

    Le client envoie des degrés, pas des kilomètres : la conversion vit là
    où l'aperçu est dessiné, ce qui garantit que la géométrie enregistrée
    est exactement celle que l'humain a vue à l'écran.
    """
    if not isinstance(offset, (list, tuple)) or len(offset) != 2:
        raise ValueError("offset_deg doit être une paire [Δlon, Δlat]")
    try:
        dlon, dlat = float(offset[0]), float(offset[1])
    except (TypeError, ValueError):
        raise ValueError("offset_deg doit contenir deux nombres") from None
    if not (math.isfinite(dlon) and math.isfinite(dlat)):
        raise ValueError("offset_deg doit contenir deux nombres finis")
    if abs(dlon) > MAX_OFFSET_DEG or abs(dlat) > MAX_OFFSET_DEG:
        raise ValueError(
            f"décalage trop grand ({dlon:+.3f}, {dlat:+.3f}) : "
            f"maximum {MAX_OFFSET_DEG}° par axe"
        )
    if dlon == 0.0 and dlat == 0.0:
        raise ValueError("décalage nul : rien à corriger")
    return dlon, dlat


def _validate_manual_geometry(raw: object) -> dict:
    """Contrôle un polygone tracé à la main avant de l'écrire.

    Sert au cas d'échec du pipeline : quand aucune géométrie n'a pu être
    vectorisée, l'humain trace un rectangle plutôt que de rejeter une méta
    par ailleurs valable. Rien n'est écrit sans que shapely ait confirmé
    que la géométrie est valide et située sur Terre.
    """
    if not isinstance(raw, dict) or raw.get("type") != "Polygon":
        raise ValueError("geometry doit être un objet GeoJSON de type Polygon")
    try:
        geom = shape(raw)
    except Exception as exc:
        raise ValueError(f"polygone illisible : {exc}") from None
    if geom.is_empty or not geom.is_valid:
        raise ValueError("polygone vide ou invalide")
    min_lon, min_lat, max_lon, max_lat = geom.bounds
    if not (-180.0 <= min_lon and max_lon <= 180.0 and -90.0 <= min_lat and max_lat <= 90.0):
        raise ValueError(
            f"polygone hors des bornes WGS84 : {geom.bounds}"
        )
    if geom.area <= 0.0:
        raise ValueError("polygone de surface nulle")
    return mapping(geom)


def build_queue() -> dict:
    metas_path, geo_path = _paths()
    metas = {m["id"]: m for m in json.loads(metas_path.read_text("utf-8"))}
    geo = json.loads(geo_path.read_text("utf-8"))

    items = []
    for feature in geo["features"]:
        props = feature["properties"]
        meta = metas.get(props["id"])
        if meta is None:
            continue
        items.append({
            "id": props["id"],
            "title": meta["title"],
            "description": meta["description"],
            "tier": meta["tier"],
            "category": meta["category"],
            "image": "/" + meta["image"] if meta.get("image") else None,
            "latlon": meta.get("maps_latlon"),
            "source_url": meta["source_url"],
            "confidence": props["confidence"],
            "warnings": props["warnings"],
            "status": props["status"],
            "geometry": feature["geometry"],
        })
    pending = [i for i in items if i["status"] == "auto"]
    pending.sort(key=lambda i: i["confidence"])
    return {"total": len(items), "reviewed": len(items) - len(pending), "items": pending}


def country_polygon() -> dict:
    """Silhouette Natural Earth du pays en cours de revue, en GeoJSON.

    Sert de repli quand aucune zone n'a pu être vectorisée : une méta
    valable sur tout le pays vaut mieux qu'une méta rejetée, et c'est déjà
    la géométrie que le pipeline donne aux métas de tier `country`.
    """
    from cartometa.geo.reference import country_geometry

    return mapping(country_geometry(STATE["country"], STATE["data"] / "cache"))


def _find_feature(geo: dict, meta_id: str) -> dict | None:
    for feature in geo["features"]:
        if feature["properties"]["id"] == meta_id:
            return feature
    return None


def apply_decision(
    meta_id: str,
    status: str,
    radius_km: float | None,
    offset_deg: object | None = None,
    geometry: object | None = None,
    use_country_polygon: bool = False,
) -> None:
    metas_path, geo_path = _paths()
    metas = {m["id"]: m for m in json.loads(metas_path.read_text("utf-8"))}
    geo = json.loads(geo_path.read_text("utf-8"))

    meta = metas.get(meta_id)
    feature = _find_feature(geo, meta_id)
    if meta is None or feature is None:
        raise UnknownMetaError(f"méta inconnue : {meta_id!r}")

    corrections = [
        name
        for name, value in (
            ("rayon", radius_km or None),
            ("décalage", offset_deg),
            ("polygone manuel", geometry),
            ("polygone du pays", True if use_country_polygon else None),
        )
        if value is not None
    ]
    if len(corrections) > 1:
        raise ValueError(
            f"corrections mutuellement exclusives ({', '.join(corrections)}) : "
            f"en appliquer une seule à la fois"
        )

    if use_country_polygon:
        # La silhouette vient de Natural Earth côté serveur, jamais du
        # client : l'aperçu affiché n'a pas à être une source de vérité.
        replacement = country_polygon()
        feature["properties"].setdefault(_GEOMETRY_BACKUP_KEY, feature["geometry"])
        feature["geometry"] = replacement
        feature["properties"]["status"] = "corrigé"
    elif geometry is not None:
        # Pas de garde « géométrie déjà présente » : tracer à la main reste
        # un acte humain explicite, et la sauvegarde ci-dessous rend U
        # capable de revenir à la géométrie automatique.
        validated = _validate_manual_geometry(geometry)
        feature["properties"].setdefault(_GEOMETRY_BACKUP_KEY, feature["geometry"])
        feature["geometry"] = validated
        feature["properties"]["status"] = "corrigé"
    elif offset_deg is not None:
        dlon, dlat = _validate_offset(offset_deg)
        if feature["geometry"] is None:
            raise ValueError(
                f"impossible de décaler {meta_id!r} : aucune géométrie à corriger"
            )
        # setdefault, jamais d'écrasement : si la méta a déjà été corrigée,
        # la sauvegarde doit rester la géométrie *d'origine*, sinon U
        # restaurerait un état déjà modifié.
        feature["properties"].setdefault(_GEOMETRY_BACKUP_KEY, feature["geometry"])
        moved = translate(shape(feature["geometry"]), xoff=dlon, yoff=dlat)
        feature["geometry"] = mapping(moved)
        feature["properties"]["status"] = "corrigé"
    elif radius_km:
        # La règle « le rayon ne s'applique qu'aux spots » doit être imposée
        # ici, côté serveur : le client ne peut pas être le seul garant de
        # l'intégrité des géométries (un POST direct pourrait sinon écraser
        # le polygone d'une méta country/regional par un cercle).
        if meta["tier"] != "spot":
            raise ValueError(
                f"le rayon ne peut être appliqué qu'aux métas de tier 'spot' "
                f"(méta {meta_id!r} est de tier {meta['tier']!r})"
            )
        if feature["geometry"] is None:
            raise ValueError(
                f"impossible d'appliquer un rayon à {meta_id!r} : aucune géométrie à corriger"
            )
        from cartometa.geo.vectorize import buffer_km

        # On ne bascule le statut en « corrigé » qu'après avoir vérifié que
        # le tampon peut réellement être calculé (cf. bug historique où une
        # méta sans géométrie ressortait « corrigée » sans rien derrière).
        feature["properties"].setdefault(_GEOMETRY_BACKUP_KEY, feature["geometry"])
        centre = shape(feature["geometry"]).centroid
        feature["geometry"] = mapping(buffer_km(Point(centre.x, centre.y), radius_km))
        feature["properties"]["status"] = "corrigé"
    else:
        feature["properties"]["status"] = status
    _write_atomic(geo_path, geo)


def apply_undo(meta_id: str) -> None:
    """Annule la dernière décision prise sur `meta_id` : remet `status` à
    `auto` et restaure la géométrie d'origine si une correction de rayon
    l'avait écrasée."""
    _, geo_path = _paths()
    geo = json.loads(geo_path.read_text("utf-8"))
    feature = _find_feature(geo, meta_id)
    if feature is None:
        raise UnknownMetaError(f"méta inconnue : {meta_id!r}")

    props = feature["properties"]
    if _GEOMETRY_BACKUP_KEY in props:
        feature["geometry"] = props.pop(_GEOMETRY_BACKUP_KEY)
    props["status"] = "auto"
    _write_atomic(geo_path, geo)


class Handler(SimpleHTTPRequestHandler):
    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/api/queue":
            self._json(build_queue())
            return
        if self.path == "/api/country-polygon":
            try:
                self._json({"geometry": country_polygon()})
            except KeyError as exc:
                # Pays absent de Natural Earth : le dire, plutôt que de
                # laisser l'interface attendre un aperçu qui ne viendra pas.
                self._json({"ok": False, "error": str(exc)}, 404)
            return
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            self.directory = str(STATIC)
        elif self.path.startswith("/app.js"):
            self.directory = str(STATIC)
        super().do_GET()

    def do_POST(self) -> None:
        if self.path not in ("/api/decision", "/api/undo"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("le corps doit être un objet JSON")
            meta_id = payload["id"]
            if self.path == "/api/decision":
                apply_decision(
                    meta_id,
                    payload["status"],
                    payload.get("radius_km"),
                    payload.get("offset_deg"),
                    payload.get("geometry"),
                    bool(payload.get("use_country_polygon")),
                )
            else:
                apply_undo(meta_id)
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "corps JSON invalide"}, 400)
            return
        except KeyError as exc:
            self._json({"ok": False, "error": f"champ manquant : {exc}"}, 400)
            return
        except UnknownMetaError as exc:
            self._json({"ok": False, "error": str(exc)}, 404)
            return
        except ValueError as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
            return
        except Exception as exc:  # garde-fou : jamais de connexion coupée en silence
            self._json({"ok": False, "error": f"erreur interne : {exc}"}, 500)
            return
        self._json({"ok": True})

    def log_message(self, *args) -> None:
        pass  # silence : le compteur de progression est dans l'interface


def main() -> None:
    parser = argparse.ArgumentParser(description="Interface de revue des géométries")
    parser.add_argument("country", nargs="?", default="PL")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    STATE["data"], STATE["country"] = args.data, args.country

    # Les images sont servies depuis la racine du projet (chemins relatifs des métas).
    os.chdir(Path.cwd())
    print(f"Revue {args.country} : http://127.0.0.1:{args.port}")
    print("Touches — A valider, R rejeter, Espace passer, U annuler")
    print("          Flèches décaler le polygone (Maj = pas large), 0 remettre à zéro")
    print("          D tracer un rectangle à la main (deux clics sur la carte)")
    print("          P prendre le polygone du pays entier")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
