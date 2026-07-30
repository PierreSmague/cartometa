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
             "properties": {"id": i, "status": status, "pieces": [{"kind": "country"}]},
             "geometry": _square(0.0, 0.0, size) if status == "validé" else None}
            for i, status, size in entries
        ],
    }), "utf-8")


@pytest.fixture
def data_dir(tmp_path):
    _write_country(tmp_path / "data", "PL", [("pl1", "validé", 3.0), ("pl2", "rejeté", 1.0)])
    _write_country(tmp_path / "data", "BW", [("bw1", "validé", 2.0)])
    return tmp_path / "data"


def test_seules_les_metas_tracees_sont_exportees(data_dir, tmp_path):
    export_viewer(data_dir, tmp_path / "viewer", ["PL", "BW"])

    index = json.loads((tmp_path / "viewer" / "data" / "index.json").read_text("utf-8"))
    assert {entry["id"] for entry in index} == {"pl1", "bw1"}


def test_l_index_est_trie_par_surface_croissante(data_dir, tmp_path):
    export_viewer(data_dir, tmp_path / "viewer", ["PL", "BW"])

    index = json.loads((tmp_path / "viewer" / "data" / "index.json").read_text("utf-8"))
    assert [entry["id"] for entry in index] == ["bw1", "pl1"]


def test_les_geometries_sont_ecrites_par_identifiant(data_dir, tmp_path):
    export_viewer(data_dir, tmp_path / "viewer", ["PL", "BW"])

    geometries = json.loads(
        (tmp_path / "viewer" / "data" / "geometries.json").read_text("utf-8")
    )
    assert set(geometries) == {"pl1", "bw1"}


def test_les_metas_manuelles_sont_exportees(tmp_path):
    data_dir = tmp_path / "data"
    _write_country(data_dir, "XX", [])
    manual = data_dir / "manual" / "XX"
    manual.mkdir(parents=True)
    (manual / "metas.json").write_text(json.dumps([
        dict(_meta("man-1a2b", tier="manual"), origin="manual",
             image="data/manual/XX/images/man-1a2b.png"),
    ]), "utf-8")
    (data_dir / "geo" / "XX.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "man-1a2b", "status": "validé",
                                     "pieces": [{"kind": "country"}]},
                      "geometry": _square(0.0, 0.0, 1.0)}],
    }), "utf-8")

    export_viewer(data_dir, tmp_path / "viewer", ["XX"])

    index = json.loads((tmp_path / "viewer" / "data" / "index.json").read_text("utf-8"))
    assert [entry["id"] for entry in index] == ["man-1a2b"]


def test_pays_sans_aucune_meta_leve(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "geo").mkdir(parents=True)
    (data_dir / "geo" / "ZZ.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": [],
    }), "utf-8")

    with pytest.raises(SystemExit, match=r"manual.*metas\.json"):
        export_viewer(data_dir, tmp_path / "viewer", ["ZZ"])


def test_pays_sans_source_importee_mais_avec_metas_manuelles_n_echoue_pas(tmp_path):
    """L'absence du fichier importé ne doit pas, à elle seule, être fatale.

    Contrairement à `test_les_metas_manuelles_sont_exportees`, qui écrit un
    `data/metas/XX.json` existant mais vide, ici `data/metas/YY.json`
    n'existe pas du tout (le dossier `metas/` n'est même pas créé) : c'est la
    seconde source, `data/manual/YY/metas.json`, qui doit à elle seule suffire
    à ce que l'export réussisse.
    """
    data_dir = tmp_path / "data"
    (data_dir / "geo").mkdir(parents=True)
    manual = data_dir / "manual" / "YY"
    manual.mkdir(parents=True)
    (manual / "metas.json").write_text(json.dumps([
        dict(_meta("man-only1", tier="manual"), origin="manual",
             image="data/manual/YY/images/man-only1.png"),
    ]), "utf-8")
    (data_dir / "geo" / "YY.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "man-only1", "status": "validé",
                                     "pieces": [{"kind": "country"}]},
                      "geometry": _square(0.0, 0.0, 1.0)}],
    }), "utf-8")

    result = export_viewer(data_dir, tmp_path / "viewer", ["YY"])

    assert result["exported"] == 1
    index = json.loads((tmp_path / "viewer" / "data" / "index.json").read_text("utf-8"))
    assert [entry["id"] for entry in index] == ["man-only1"]


def test_discover_countries_trie_et_met_en_majuscules(data_dir):
    assert discover_countries(data_dir) == ["BW", "PL"]
