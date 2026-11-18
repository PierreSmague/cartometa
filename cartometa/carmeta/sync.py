"""`cartometa-carmeta sync`: mirror the repository, redo the analysis.

The scheduled command. It writes nowhere but under `data/cache/carmeta/` (and
`logs/`): never `data/carmeta/`, never `data/geo/`, no git command — so it can
run while the maintainer works on another branch.
"""
from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cartometa.atomic_write import write_json_atomic
from cartometa.carmeta import github, mirror
from cartometa.carmeta.analysis import analyse_country, served_countries
from cartometa.carmeta.countries import CountryAssigner
from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.rules import Rules
from cartometa.carmeta.verdicts import pending_cases

# A lock older than this is a crashed run, not a running one.
STALE_LOCK_SECONDS = 6 * 3600
# Compact files kept in memory at once: a multi-country file is read by every
# country it feeds, and reloading it each time is what would make `--force` slow.
LOADER_CACHE = 3


class SyncBusy(RuntimeError):
    """Another sync holds the lock."""


@dataclass
class SyncResult:
    changed: bool = False
    new: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    postponed: list[str] = field(default_factory=list)
    analysed: list[str] = field(default_factory=list)
    pending: int = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Lock:
    def __init__(self, paths: CarmetaPaths) -> None:
        self.path = paths.lock

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime > STALE_LOCK_SECONDS:
            self.path.unlink(missing_ok=True)
        try:
            handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise SyncBusy(f"another sync is running ({self.path})") from None
        with os.fdopen(handle, "w") as stream:
            stream.write(f"{os.getpid()} {_now()}\n")
        return self

    def __exit__(self, *exc) -> None:
        self.path.unlink(missing_ok=True)


def _loader(paths: CarmetaPaths):
    cache: OrderedDict[str, mirror.CompactFile] = OrderedDict()

    def load(sha: str) -> mirror.CompactFile:
        if sha in cache:
            cache.move_to_end(sha)
            return cache[sha]
        cache[sha] = mirror.load_compact(paths, sha)
        if len(cache) > LOADER_CACHE:
            cache.popitem(last=False)
        return cache[sha]

    return load


def load_analyses(paths: CarmetaPaths) -> dict[str, dict]:
    if not paths.analysis_dir.exists():
        return {}
    return {
        path.stem: json.loads(path.read_text("utf-8"))
        for path in sorted(paths.analysis_dir.glob("*.json"))
    }


def _drop_orphan_compacts(paths: CarmetaPaths, state: dict) -> None:
    wanted = {entry["sha"] for entry in state["files"].values()}
    if not paths.files.exists():
        return
    for path in paths.files.glob("*.npz"):
        if path.stem not in wanted:
            path.unlink()


def run_sync(paths: CarmetaPaths, rules: Rules, fetch: github.Fetch, *,
             force: bool = False, progress=lambda message: None) -> SyncResult:
    state = mirror.load_state(paths)
    tree = github.fetch_tree(fetch)
    if tree.sha == state["tree_sha"] and not state["dirty"] and not force:
        # Nothing changed: one network call, and not a byte written — the lock
        # itself is only taken once there is work to do.
        return SyncResult()

    with _Lock(paths):
        result = SyncResult(changed=True)
        changes = mirror.diff(state, tree)
        result.new, result.modified, result.deleted = (
            changes.new, changes.modified, changes.deleted)
        dirty = set(state["dirty"])

        def touched(entry: dict | None) -> None:
            dirty.update((entry or {}).get("countries", {}))

        for path in changes.deleted:
            touched(state["files"].pop(path))
        state["dirty"] = sorted(dirty)
        if changes.deleted:
            mirror.save_state(paths, state)

        assigner = None
        for path in changes.to_fetch:
            blob = tree.blobs[path]
            progress(f"téléchargement : {path}")
            # The date first: it is the call the hourly quota can refuse, and a
            # refusal must not throw away a download of a hundred megabytes.
            date = github.commit_date(fetch, path)
            try:
                raw = github.download(fetch, path, blob.sha)
            except github.ContentChanged:
                # Committed again since the listing: the next run will see it.
                result.postponed.append(path)
                continue
            if assigner is None:
                assigner = CountryAssigner(paths.natural_earth_cache)
            compact = mirror.decode_points(raw, assigner)
            del raw
            if compact is not None:
                mirror.store_compact(paths, blob.sha, compact)
            touched(state["files"].get(path))
            entry = mirror.file_entry(blob.sha, date, _now(), compact)
            touched(entry)
            state["files"][path] = entry
            state["dirty"] = sorted(dirty)
            # After every file: a quota spent halfway through the first pass
            # resumes where it stopped instead of downloading 1.3 GB again.
            mirror.save_state(paths, state)

        if assigner is None:
            assigner = CountryAssigner(paths.natural_earth_cache)
        served = served_countries(state, rules)
        known = {path.stem for path in paths.analysis_dir.glob("*.json")} \
            if paths.analysis_dir.exists() else set()
        # A country no file feeds any more still gets an analysis — an empty
        # one: that is the evidence its tags are gone, which a missing file is not.
        # A file's handful of points across a border makes that neighbour
        # "touched" without making it served: it gets no analysis at all.
        relevant = set(served) | known
        todo = sorted(relevant if force else (dirty & relevant) | (set(served) - known))
        load = _loader(paths)
        for country in todo:
            progress(f"analyse : {country}")
            write_json_atomic(paths.analysis(country),
                              analyse_country(country, state, rules, load, assigner.iso),
                              indent=None)
        result.analysed = todo

        cases = pending_cases(load_analyses(paths), rules)
        write_json_atomic(paths.pending, cases)
        result.pending = len(cases)

        _drop_orphan_compacts(paths, state)
        state["dirty"] = []
        # Not the tree sha when a file was postponed: the next run must look again.
        state["tree_sha"] = None if result.postponed else tree.sha
        state["checked_at"] = _now()
        mirror.save_state(paths, state)
        return result
