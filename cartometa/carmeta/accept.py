"""`cartometa-carmeta accept`: validate carmeta proposals in bulk, as computed.

The review interface stays the way to look at a footprint and retouch it. This
is for the maintainer who has looked at enough of a batch to trust the rest:
every pending carmeta proposal is validated exactly as `A` would in the review
— pieces resolved against Natural Earth, clipped to the borders — without
opening it.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import mapping

from cartometa.carmeta.importer import CarmetaImportError
from cartometa.models import STATUS_PROPOSED, STATUS_TRACED, GeoRecord
from cartometa.review.pieces import PieceError, resolve_pieces
from cartometa.review.server import DEFAULT_PORT as REVIEW_PORT
from cartometa.review.server import port_is_taken
from cartometa.review.store import CountryPaths, load_geo, read_json_list, save_geo


@dataclass
class AcceptResult:
    # (country, id, title) of each meta validated / of each re-proposal adopted.
    accepted: list[tuple[str, str, str]] = field(default_factory=list)
    adopted: list[tuple[str, str, str]] = field(default_factory=list)
    # (country, id, title, reason): left as they were.
    failed: list[tuple[str, str, str, str]] = field(default_factory=list)


def _countries(data_dir: Path) -> list[str]:
    directory = data_dir / "carmeta"
    return sorted(path.stem for path in directory.glob("??.json")) if directory.exists() else []


def run_accept(data_dir: Path, countries: list[str] | None,
               out: Callable[[str], None] = lambda line: None) -> AcceptResult:
    """Validate every `proposé` carmeta meta, adopt every pending re-proposal.

    Only metas of `data/carmeta/` are touched: a proposal that came from
    `cartometa-import-tagged`, or a meta still to be drawn, stays in the queue.
    """
    if port_is_taken("127.0.0.1", REVIEW_PORT):
        raise CarmetaImportError(
            f"une session cartometa-review semble active (le port {REVIEW_PORT} "
            f"répond) : les deux écrivent data/geo, arrêtez-la avant d'accepter.")
    result = AcceptResult()
    wanted = [code.upper() for code in countries] if countries else _countries(data_dir)
    for country in wanted:
        paths = CountryPaths(data_dir, country)
        records = load_geo(paths)
        changed = 0
        for meta in read_json_list(paths.carmeta_metas):
            record = records.get(meta["id"])
            if record is None:
                continue
            if record.status == STATUS_PROPOSED:
                pieces, bucket = record.pieces, result.accepted
            elif record.status == STATUS_TRACED and record.proposal is not None:
                pieces, bucket = record.proposal.get("pieces", []), result.adopted
            else:
                continue
            try:
                geometry = resolve_pieces(pieces, country, paths.cache)
            except PieceError as exc:
                # Typically a footprint lying entirely off the country outline.
                result.failed.append((country, meta["id"], meta["title"], str(exc)))
                continue
            records[meta["id"]] = GeoRecord(
                id=meta["id"],
                # Through JSON: mapping() yields tuples, which save_geo's
                # rounding does not walk — the file would only settle on its
                # second save.
                geometry=json.loads(json.dumps(mapping(geometry))),
                pieces=list(pieces), status=STATUS_TRACED,
            )
            bucket.append((country, meta["id"], meta["title"]))
            changed += 1
        if changed:
            save_geo(paths, records)
            out(f"{country}  {changed} meta(s) validée(s)")
    return result
