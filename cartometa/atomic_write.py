from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, payload: Any, *, indent: int | None = 2) -> None:
    """Write `payload` as JSON to `path` through a temp file, then replace.

    An interruption (power cut, Ctrl-C, disk full) in the middle of the write
    must never leave `path` truncated or corrupted: the temp file may well be
    left half-written, but `path` is only replaced once the write has finished
    successfully (`os.replace` is atomic within one volume).

    Used by the review server (`cartometa/review/server.py`), which carries the
    repository's only irreplaceable human work: the hand-drawn geometries.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=indent, ensure_ascii=False), "utf-8")
    os.replace(temporary, path)
