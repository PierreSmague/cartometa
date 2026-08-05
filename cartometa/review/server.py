from __future__ import annotations

import argparse
import json
import socket
import sys
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

# Outside `static/`, the interface only needs the metas' images: imported ones
# live under `input/`, hand-entered ones under `data/manual/`. Nothing else in the
# repository must be reachable through this GET.
ALLOWED_ROOT_PREFIXES = ("/input/", "/data/manual/")

# Same cap as `manual.MAX_IMAGE_BYTES`, applied before reading the body: we refuse
# on the header rather than after having swallowed the bytes.
MAX_BODY_BYTES = 8 * 1024 * 1024

# The AnkiConnect add-on answers on 8765, and the interface used to default there too:
# a review session with Anki open reached Anki, not this server. We keep a port of our
# own, and `ANKICONNECT_PORT` stays here so the collision can be named in the error.
ANKICONNECT_PORT = 8765
DEFAULT_PORT = 8799


def paths() -> CountryPaths:
    return STATE["paths"]


def apply_decision(meta_id: str, status: str, pieces: list) -> None:
    """Record a decision, resolving the pieces server-side.

    A rejection needs no geometry. A validation, on the other hand, never goes
    through the geometry displayed in the browser: the descriptors are re-read from
    Natural Earth, then united. Nothing is written if the resolution fails.
    """
    if status == STATUS_REJECTED:
        set_decision(paths(), meta_id, STATUS_REJECTED, None, [])
        return
    if status == STATUS_TRACED:
        geometry = resolve_pieces(pieces, paths().country, paths().cache)
        set_decision(paths(), meta_id, STATUS_TRACED, mapping(geometry), list(pieces))
        return
    # Status neither validated nor rejected: delegate to set_decision, the only
    # place that validates the status, so as not to duplicate the check with a less
    # useful message that does not name the accepted values.
    set_decision(paths(), meta_id, status, None, [])


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
            raise ValueError(f"body too large: {length} bytes")
        return self.rfile.read(length) if length else b""

    def list_directory(self, path):
        # No directory listing: `input/` and `data/manual/` must expose only the
        # files asked for by name, never their full contents.
        self.send_error(404)
        return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route, query = parsed.path, parse_qs(parsed.query)
        if route == "/api/category":
            # Pass-through to the extraction's inference: the manual form suggests
            # a category rather than imposing one.
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
                # The admin-1 dataset weighs 41 MB: its first download can fail, and
                # the interface has to say so rather than wait for a hover that will
                # never highlight anything.
                self._json(
                    {"ok": False, "error": f"admin-1 download failed: {exc}"}, 502
                )
            return

        if route in ("/", "/index.html"):
            self.path = "/index.html"
            route = "/index.html"
        # A ".." (raw or percent-encoded) would turn the file probe below into an
        # existence oracle over the disk: refused outright rather than silently
        # normalised.
        if ".." in unquote(route).split("/"):
            self.send_error(404)
            return
        # The interface's files are served from `static/`; outside it, only the
        # metas' images (`input/`, `data/manual/`) are legitimate — the rest of the
        # repository has no business behind this GET.
        if (STATIC / route.lstrip("/")).is_file():
            self.directory = str(STATIC)
        elif not route.startswith(ALLOWED_ROOT_PREFIXES):
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self) -> None:
        origin = self.headers.get("Origin")
        if origin is not None:
            # Per the Fetch spec, a browser ALWAYS adds `Origin` on a non-GET/HEAD
            # request, same-origin included: its mere presence therefore proves
            # nothing. It is the VALUE that has to be compared to the expected host —
            # compared against the request's `Host`, since the server only listens on
            # 127.0.0.1.
            attendu = self.headers.get("Host", "")
            if urlparse(origin).netloc != attendu:
                self._json(
                    {"ok": False, "error": f"cross-origin request refused: {origin!r}"}, 403
                )
                return
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
                raise ValueError("the body must be a JSON object")

            if route == "/api/resolve":
                # Preview only: nothing is written. The browser cannot compute an
                # intersection; when an area is clipped, it asks here for the exact
                # geometry an `A` would save.
                geometry = resolve_pieces(
                    payload.get("pieces") or [], paths().country, paths().cache
                )
                self._json({"ok": True, "geometry": mapping(geometry)})
                return
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
            self._json({"ok": False, "error": "invalid JSON body"}, 400)
        except KeyError as exc:
            self._json({"ok": False, "error": f"missing field: {exc}"}, 400)
        except UnknownMetaError as exc:
            self._json({"ok": False, "error": str(exc)}, 404)
        except (PieceError, ManualMetaError, ValueError) as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # safety rail: never a silently dropped connection
            self._json({"ok": False, "error": f"internal error: {exc}"}, 500)
        else:
            self._json({"ok": True})

    def log_message(self, *args) -> None:
        pass  # silence: the progress counter lives in the interface


TOUCHES = """Keys - D rectangle, C freehand outline, Enter close the outline, S subdivisions, E whole country
       F clip the area to the country borders (press again to unclip)
       Backspace remove the last piece, Escape leave the mode, 0 empty
       A save, R reject, Space next (Shift+Space previous), U undo
       N new manual meta"""


def port_is_taken(host: str, port: int) -> bool:
    """Is something already listening there?

    Binding is not a reliable answer: `HTTPServer` sets `SO_REUSEADDR`, and on Windows
    that lets a second bind on a *listening* port succeed — the first listener keeps
    serving the traffic while we announce a URL we do not answer. Opening a connection
    asks the only question that matters. A port merely left in TIME_WAIT by a previous
    run accepts no connection, so stopping and relaunching still reads as free.
    """
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex((host, port)) == 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Geometry review interface")
    parser.add_argument("country", nargs="?", default="PL")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Reopen every meta, including those already drawn or rejected.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if port_is_taken("127.0.0.1", args.port):
        # ASCII only: the Windows console renders this in cp1252, where an em dash
        # comes out as mojibake.
        held_by = " (AnkiConnect's port)" if args.port == ANKICONNECT_PORT else ""
        print(
            f"Port {args.port} is already in use{held_by}: nothing was started.\n"
            f"Close the other program, or pick a free port with --port.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    STATE["paths"] = CountryPaths(args.data, args.country.upper())
    STATE["include_all"] = args.all

    print(f"Reviewing {STATE['paths'].country}: http://127.0.0.1:{args.port}")
    print(TOUCHES)
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
