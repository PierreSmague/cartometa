from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CarmetaPaths:
    """Every path the carmeta pipeline touches, in one single place.

    Two worlds that must not be confused: `cache` is gitignored, rebuilt from
    the carmeta repository, and the only place `sync` may write; `rules` and
    `metas()` are versioned and only ever written by a command the maintainer
    launches by hand.
    """

    data: Path

    @property
    def cache(self) -> Path:
        return self.data / "cache" / "carmeta"

    @property
    def files(self) -> Path:
        return self.cache / "files"

    def compact(self, sha: str) -> Path:
        return self.files / f"{sha}.npz"

    @property
    def state(self) -> Path:
        return self.cache / "state.json"

    @property
    def analysis_dir(self) -> Path:
        return self.cache / "analysis"

    def analysis(self, country: str) -> Path:
        return self.analysis_dir / f"{country}.json"

    @property
    def report(self) -> Path:
        return self.cache / "report.html"

    @property
    def pending(self) -> Path:
        return self.cache / "pending.json"

    @property
    def lock(self) -> Path:
        return self.cache / "sync.lock"

    @property
    def rules(self) -> Path:
        return self.data / "carmeta" / "rules.json"

    def metas(self, country: str) -> Path:
        return self.data / "carmeta" / f"{country}.json"

    @property
    def natural_earth_cache(self) -> Path:
        return self.data / "cache"
