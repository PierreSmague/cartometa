import json
from pathlib import Path

import pytest

from cartometa.geo.export import discover_countries, export_viewer


def _square(x: float, y: float, size: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y],
        ]],
    }


def _meta(meta_id: str, tier: str = "regional") -> dict:
    return {
        "id": meta_id, "tier": tier, "title": f"titre {meta_id}",
        "description": "description", "category": "autre",
        "image": f"input/{meta_id}.webp",
        "source_url": f"https://www.plonkit.net/x#{meta_id}",
    }


def _write_country(data_dir: Path, country: str, entries: list[tuple[str, str, float]]) -> None:
    """entries: (id, statut, taille du carré) — la taille pilote l'ordre de tri."""
    (data_dir / "metas").mkdir(parents=True, exist_ok=True)
    (data_dir / "geo").mkdir(parents=True, exist_ok=True)
    (data_dir / "metas" / f"{country}.json").write_text(
        json.dumps([_meta(i) for i, _, _ in entries]), "utf-8"
    )
    (data_dir / "geo" / f"{country}.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {"id": i, "confidence": 1.0, "warnings": [], "status": status},
             "geometry": _square(0.0, 0.0, size)}
            for i, status, size in entries
        ],
    }), "utf-8")


@pytest.fixture
def data_dir(tmp_path):
    _write_country(tmp_path / "data", "PL", [("pl1", "validé", 3.0), ("pl2", "rejeté", 1.0)])
    _write_country(tmp_path / "data", "BW", [("bw1", "corrigé", 2.0), ("bw2", "auto", 1.0)])
    return tmp_path / "data"


def test_decouvre_tous_les_pays_traites(data_dir):
    assert discover_countries(data_dir) == ["BW", "PL"]


def test_decouverte_vide_si_aucune_geometrie(tmp_path):
    (tmp_path / "geo").mkdir()
    assert discover_countries(tmp_path) == []


def test_export_multi_pays_fusionne_les_deux(data_dir, tmp_path):
    result = export_viewer(data_dir, tmp_path / "out", discover_countries(data_dir))

    assert result["exported"] == 2
    assert result["by_country"] == {"BW": 1, "PL": 1}
    index = json.loads((tmp_path / "out" / "data" / "index.json").read_text("utf-8"))
    assert [e["id"] for e in index] == ["bw1", "pl1"]  # tri par surface croissante
    assert {e["country"] for e in index} == {"BW", "PL"}


def test_les_non_revues_restent_exclues_par_defaut(data_dir, tmp_path):
    """Exporter tous les pays d'un coup ne doit pas relâcher la porte de revue."""
    result = export_viewer(data_dir, tmp_path / "out", discover_countries(data_dir))

    geometries = json.loads((tmp_path / "out" / "data" / "geometries.json").read_text("utf-8"))
    assert "bw2" not in geometries  # statut auto
    assert "pl2" not in geometries  # statut rejeté
    assert result["unreviewed_included"] == 0


def test_include_auto_compte_les_non_revues(data_dir, tmp_path):
    result = export_viewer(data_dir, tmp_path / "out", ["BW"], include_auto=True)

    assert result["exported"] == 2
    assert result["unreviewed_included"] == 1


def test_metas_manquantes_echouent_explicitement(data_dir, tmp_path):
    (data_dir / "metas" / "BW.json").unlink()

    with pytest.raises(SystemExit, match="cartometa-extract"):
        export_viewer(data_dir, tmp_path / "out", ["BW"])
