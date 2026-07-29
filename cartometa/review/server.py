from __future__ import annotations

import argparse
import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from shapely.geometry import Point, mapping, shape

STATIC = Path(__file__).resolve().parent / "static"
STATE = {"data": Path("data"), "country": "PL"}


def _paths() -> tuple[Path, Path]:
    data, country = STATE["data"], STATE["country"]
    return data / "metas" / f"{country}.json", data / "geo" / f"{country}.geojson"


def _write_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), "utf-8")
    os.replace(temporary, path)


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


def apply_decision(meta_id: str, status: str, radius_km: float | None) -> None:
    _, geo_path = _paths()
    geo = json.loads(geo_path.read_text("utf-8"))
    for feature in geo["features"]:
        if feature["properties"]["id"] != meta_id:
            continue
        feature["properties"]["status"] = status
        if radius_km and feature["geometry"]:
            from cartometa.geo.vectorize import buffer_km

            centre = shape(feature["geometry"]).centroid
            feature["geometry"] = mapping(buffer_km(Point(centre.x, centre.y), radius_km))
            feature["properties"]["status"] = "corrigé"
        break
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
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            self.directory = str(STATIC)
        elif self.path.startswith("/app.js"):
            self.directory = str(STATIC)
        super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/api/decision":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        apply_decision(payload["id"], payload["status"], payload.get("radius_km"))
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
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
