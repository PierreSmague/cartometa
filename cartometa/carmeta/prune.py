"""`cartometa-carmeta prune`: delete validated metas whose coverage is gone.

A validated meta is never removed on its own: a tag missing from one version
of a file is not proof the coverage disappeared. But when it did — `©2019`
entirely re-shot — the maintainer must be able to take the meta down. Deletion,
not rejection: should the tag come back one day, it is proposed afresh.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from cartometa.atomic_write import write_json_atomic
from cartometa.carmeta.importer import (
    VANISHED_KEPT,
    Action,
    CarmetaImportError,
    plan_import,
)
from cartometa.carmeta.rules import Rules
from cartometa.review.server import DEFAULT_PORT as REVIEW_PORT
from cartometa.review.server import port_is_taken
from cartometa.review.store import CountryPaths, load_geo, read_json_list, save_geo

YES = ("o", "oui", "y", "yes")


def vanished_validated(data_dir: Path, countries: list[str] | None,
                       rules: Rules) -> list[Action]:
    """Validated carmeta metas whose tag no retained row stands behind any more.

    Straight from the import plan, so that `prune`, `status` and the report
    agree. A country with no cached analysis is not in the plan: it is never
    pruned on an absence of evidence.
    """
    plan = plan_import(data_dir, countries, rules)
    return [action for action in plan.actions if action.kind == VANISHED_KEPT]


def _delete(data_dir: Path, action: Action) -> None:
    paths = CountryPaths(data_dir, action.country)
    metas = [m for m in read_json_list(paths.carmeta_metas) if m["id"] != action.meta_id]
    if metas:
        write_json_atomic(paths.carmeta_metas, metas)
    else:
        paths.carmeta_metas.unlink(missing_ok=True)
    records = load_geo(paths)
    if records.pop(action.meta_id, None) is not None:
        save_geo(paths, records)


def run_prune(data_dir: Path, countries: list[str] | None, rules: Rules,
              ask: Callable[[str], str], out: Callable[[str], None], *,
              assume_yes: bool = False) -> list[Action]:
    """Ask about each vanished validated meta; returns the ones deleted."""
    if port_is_taken("127.0.0.1", REVIEW_PORT):
        raise CarmetaImportError(
            f"une session cartometa-review semble active (le port {REVIEW_PORT} "
            f"répond) : les deux écrivent data/geo, arrêtez-la avant de supprimer.")
    candidates = vanished_validated(data_dir, countries, rules)
    if not candidates:
        out("Aucune meta validée dont le tag a disparu.")
        return []
    deleted = []
    for action in candidates:
        out(f"{action.country}  {action.meta_id}  {action.title}  ({action.detail})")
        if not assume_yes:
            try:
                answer = ask("  Supprimer cette meta publiée ? [o/N] > ").strip().lower()
            except EOFError:
                break
            if answer not in YES:
                continue
        _delete(data_dir, action)
        deleted.append(action)
        out("  supprimée")
    out(f"{len(deleted)} meta(s) supprimée(s) sur {len(candidates)}.")
    return deleted
