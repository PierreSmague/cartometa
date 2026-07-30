from __future__ import annotations

import argparse
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from shapely.geometry import mapping

from cartometa.extract.categories import infer_category
from cartometa.geo.admin1 import country_regions
from cartometa.geo.reference import country_geometry
from cartometa.models import STATUS_REJECTED, STATUS_TRACED
from cartometa.review.manual import ManualMetaError, create_meta, save_image
from cartometa.review.pieces import PieceError, resolve_pieces
from cartometa.review.store import (
    CountryPaths,
    UnknownMetaError,
    build_queue,
    clear_decision,
    set_decision,
)

STATIC = Path(__file__).resolve().parent / "static"
STATE: dict = {"paths": None, "include_all": False}

# En dehors de `static/`, l'interface n'a besoin que des images des métas :
# celles importées vivent sous `input/`, celles saisies à la main sous
# `data/manual/`. Rien d'autre du dépôt ne doit être atteignable par ce GET.
ALLOWED_ROOT_PREFIXES = ("/input/", "/data/manual/")

# Même plafond que `manual.MAX_IMAGE_BYTES`, appliqué avant de lire le corps :
# on refuse sur l'en-tête plutôt qu'après avoir absorbé les octets.
MAX_BODY_BYTES = 8 * 1024 * 1024


def paths() -> CountryPaths:
    return STATE["paths"]


def apply_decision(meta_id: str, status: str, pieces: list) -> None:
    """Enregistre une décision, en résolvant les morceaux côté serveur.

    Un rejet ne demande aucune géométrie. Une validation, elle, ne passe
    jamais par la géométrie affichée dans le navigateur : les descripteurs
    sont relus depuis Natural Earth, puis unis. Rien n'est écrit si la
    résolution échoue.
    """
    if status == STATUS_REJECTED:
        set_decision(paths(), meta_id, STATUS_REJECTED, None, [])
        return
    if status != STATUS_TRACED:
        raise ValueError(f"statut inconnu : {status!r}")
    geometry = resolve_pieces(pieces, paths().country, paths().cache)
    set_decision(paths(), meta_id, STATUS_TRACED, mapping(geometry), list(pieces))


class Handler(SimpleHTTPRequestHandler):
    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError(f"corps trop volumineux : {length} octets")
        return self.rfile.read(length) if length else b""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route, query = parsed.path, parse_qs(parsed.query)
        if route == "/api/category":
            # Passe-plat vers l'inférence de l'extraction : le formulaire
            # manuel propose une catégorie plutôt que d'en imposer une.
            text = (query.get("text") or [""])[0]
            self._json({"category": infer_category(text, text)})
            return
        if route == "/api/queue":
            self._json(build_queue(paths(), STATE["include_all"]))
            return
        if route == "/api/country-polygon":
            try:
                geometry = country_geometry(paths().country, paths().cache)
            except KeyError as exc:
                self._json({"ok": False, "error": str(exc)}, 404)
                return
            self._json({"geometry": mapping(geometry)})
            return
        if route == "/api/admin1":
            try:
                self._json(country_regions(paths().country, paths().cache))
            except KeyError as exc:
                self._json({"ok": False, "error": str(exc)}, 404)
            except OSError as exc:
                # Le dataset admin-1 pèse 41 Mo : son premier téléchargement
                # peut échouer, et l'interface doit le dire plutôt que
                # d'attendre un survol qui ne surlignera jamais rien.
                self._json(
                    {"ok": False, "error": f"téléchargement admin-1 impossible : {exc}"}, 502
                )
            return

        if route in ("/", "/index.html"):
            self.path = "/index.html"
            route = "/index.html"
        # Un ".." (brut ou pourcent-encodé) transformerait la sonde de
        # fichier ci-dessous en oracle d'existence sur le disque : refusé
        # d'emblée plutôt que normalisé en silence.
        if ".." in unquote(route).split("/"):
            self.send_error(404)
            return
        # Les fichiers de l'interface sont servis depuis `static/` ; en
        # dehors, seules les images des métas (`input/`, `data/manual/`)
        # sont légitimes — le reste du dépôt n'a rien à faire derrière ce GET.
        if (STATIC / route.lstrip("/")).is_file():
            self.directory = str(STATIC)
        elif not route.startswith(ALLOWED_ROOT_PREFIXES):
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route, query = parsed.path, parse_qs(parsed.query)
        try:
            if route == "/api/meta/image":
                meta_id = (query.get("id") or [""])[0]
                stored = save_image(paths(), meta_id, self._body())
                self._json({"ok": True, "image": "/" + stored})
                return

            payload = json.loads(self._body() or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("le corps doit être un objet JSON")

            if route == "/api/decision":
                apply_decision(payload["id"], payload["status"], payload.get("pieces") or [])
            elif route == "/api/undo":
                clear_decision(paths(), payload["id"])
            elif route == "/api/meta":
                meta = create_meta(
                    paths(),
                    title=payload.get("title"),
                    description=payload.get("description"),
                    category=payload.get("category"),
                    source_url=payload.get("source_url", ""),
                )
                self._json({"ok": True, "meta": meta})
                return
            else:
                self.send_error(404)
                return
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "corps JSON invalide"}, 400)
        except KeyError as exc:
            self._json({"ok": False, "error": f"champ manquant : {exc}"}, 400)
        except UnknownMetaError as exc:
            self._json({"ok": False, "error": str(exc)}, 404)
        except (PieceError, ManualMetaError, ValueError) as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # garde-fou : jamais de connexion coupée en silence
            self._json({"ok": False, "error": f"erreur interne : {exc}"}, 500)
        else:
            self._json({"ok": True})

    def log_message(self, *args) -> None:
        pass  # silence : le compteur de progression est dans l'interface


TOUCHES = """Touches — D rectangle, C contour libre, S subdivisions, P pays entier
          Retour arrière retirer le dernier morceau, Échap sortir du mode, 0 vider
          A enregistrer, R rejeter, Espace suivante (Maj+Espace précédente), U annuler
          N nouvelle méta manuelle"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Interface de revue des géométries")
    parser.add_argument("country", nargs="?", default="PL")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Rouvrir toutes les métas, y compris celles déjà tracées ou rejetées.",
    )
    args = parser.parse_args()
    STATE["paths"] = CountryPaths(args.data, args.country.upper())
    STATE["include_all"] = args.all

    print(f"Revue {STATE['paths'].country} : http://127.0.0.1:{args.port}")
    print(TOUCHES)
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
