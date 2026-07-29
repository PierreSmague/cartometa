from __future__ import annotations
import json
from pathlib import Path

import pytest

from cartometa.atomic_write import write_json_atomic


def test_writes_json_readable_back(tmp_path: Path):
    path = tmp_path / "out.json"
    write_json_atomic(path, {"a": 1})
    assert json.loads(path.read_text("utf-8")) == {"a": 1}


def test_creates_parent_directories(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "out.json"
    write_json_atomic(path, {"a": 1})
    assert json.loads(path.read_text("utf-8")) == {"a": 1}


def test_no_leftover_temp_file_after_success(tmp_path: Path):
    path = tmp_path / "out.json"
    write_json_atomic(path, {"a": 1})
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_original_file_survives_a_failed_write(tmp_path: Path, monkeypatch):
    """Une écriture qui échoue en cours de route (disque plein, interruption)
    ne doit jamais laisser le fichier final tronqué : il doit soit ne pas
    exister, soit conserver son contenu précédent intact — jamais un état
    partiel."""
    path = tmp_path / "out.json"
    write_json_atomic(path, {"important": "travail de revue humain"})

    real_replace = __import__("os").replace

    def boom(*args, **kwargs):
        raise OSError("disque plein")

    monkeypatch.setattr("cartometa.atomic_write.os.replace", boom)
    with pytest.raises(OSError):
        write_json_atomic(path, {"important": "donnee corrompue en cours d'ecriture"})

    # Le fichier final n'a pas bougé : toujours l'ancien contenu valide.
    assert json.loads(path.read_text("utf-8")) == {"important": "travail de revue humain"}
