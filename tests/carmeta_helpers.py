"""Shared fixtures of the carmeta tests: a fake GitHub and synthetic point files."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import quote

import numpy as np

from cartometa.carmeta import github
from cartometa.carmeta.zones import KM_PER_DEG_LAT, KM_PER_DEG_LON
from cartometa.geo.reference import DATASET_NAME

# Two square countries, 10° wide, far enough apart never to snap to each other.
COUNTRIES = {"AA": (0.0, 0.0, 10.0, 10.0), "BB": (20.0, 0.0, 30.0, 10.0)}


def write_countries(cache_dir, countries=COUNTRIES):
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / DATASET_NAME).write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"ISO_A2": code, "ISO_A2_EH": code},
             "geometry": {"type": "Polygon", "coordinates": [[
                 [w, s], [e, s], [e, n], [w, n], [w, s]]]}}
            for code, (w, s, e, n) in countries.items()
        ],
    }), "utf-8")


def point(lat, lng, tags, pano=None, heading=90.0):
    return {"lat": lat, "lng": lng, "heading": heading, "pitch": 0,
            "panoId": pano or f"pano{lat:.5f}_{lng:.5f}",
            "extra": {"tags": list(tags)}}


def lattice(tags_of, n=40, step_km=1.0, lat0=2.0, lng0=2.0):
    """An n × n lattice of points; `tags_of(row, column)` gives each one's tags."""
    kx = KM_PER_DEG_LON * np.cos(np.radians(lat0))
    return [
        point(lat0 + row * step_km / KM_PER_DEG_LAT, lng0 + column * step_km / kx,
              tags_of(row, column))
        for row in range(n) for column in range(n)
    ]


def points_file(points, name="test file", colors=None):
    declared = {tag: {"order": i, "color": color}
                for i, (tag, color) in enumerate((colors or {}).items())}
    return json.dumps({"name": name, "customCoordinates": points,
                       "extra": {"tags": declared}}).encode("utf-8")


class FakeGithub:
    """A repository held in memory, answering the three endpoints `sync` uses."""

    def __init__(self, files=None, dates=None):
        self.files: dict[str, bytes] = dict(files or {})
        self.dates: dict[str, str] = dict(dates or {})
        self.calls: list[str] = []
        self.headers: list[dict] = []
        self.fail_after: int | None = None

    def tree_sha(self):
        digest = hashlib.sha1()
        for path in sorted(self.files):
            digest.update(path.encode() + github.blob_sha(self.files[path]).encode())
        return digest.hexdigest()

    def __call__(self, url, headers):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise github.RateLimited("1790000000")
        self.calls.append(url)
        self.headers.append(dict(headers))
        if url.startswith(f"{github.API}/git/trees/"):
            return json.dumps({
                "sha": self.tree_sha(), "truncated": False,
                "tree": [{"path": path, "type": "blob", "size": len(raw),
                          "sha": github.blob_sha(raw)}
                         for path, raw in sorted(self.files.items())],
            }).encode()
        if url.startswith(f"{github.API}/commits?path="):
            for path in self.files:
                if f"path={quote(path, safe='')}&" in url:
                    date = self.dates.get(path, "2026-05-06T13:05:16Z")
                    return json.dumps([{"commit": {"committer": {"date": date}}}]).encode()
            return b"[]"
        if url.startswith(github.RAW + "/"):
            for path, raw in self.files.items():
                if url == f"{github.RAW}/{quote(path, safe='/')}":
                    return raw
        raise github.GithubError(f"{url}: HTTP 404")

    @property
    def api_calls(self):
        return [url for url in self.calls if url.startswith(github.API)]

    @property
    def downloads(self):
        return [url for url in self.calls if url.startswith(github.RAW)]
