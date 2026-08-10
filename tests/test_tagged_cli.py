import json

import pytest

from cartometa.geo.reference import DATASET_NAME
from cartometa.review.store import CountryPaths
from cartometa.tagged.cli import main


def _point(lat, lng, tags):
    return {"lat": lat, "lng": lng, "extra": {"tags": tags}}


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    (d / "cache").mkdir(parents=True)
    (d / "cache" / DATASET_NAME).write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"ISO_A2": "AA", "ISO_A2_EH": "AA"},
             "geometry": {"type": "Polygon", "coordinates": [[
                 [0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0],
             ]]}},
        ],
    }), "utf-8")
    return d


def _source(tmp_path):
    f = tmp_path / "source.json"
    f.write_text(json.dumps({"name": "fichier test", "customCoordinates": [
        _point(5.0, 5.0, ["Ring"]), _point(5.01, 5.01, ["Ring"]),
    ]}), "utf-8")
    return f


def test_the_cli_imports_and_prints_the_recap(data_dir, tmp_path, capsys):
    main([str(_source(tmp_path)), "--mode", "route", "--category", "car",
          "--data-dir", str(data_dir)])

    out = capsys.readouterr().out
    assert "Ring" in out and "AA" in out
    assert CountryPaths(data_dir, "AA").geo.exists()


def test_an_unknown_category_is_refused(data_dir, tmp_path):
    with pytest.raises(SystemExit):
        main([str(_source(tmp_path)), "--mode", "route", "--category", "bidon",
              "--data-dir", str(data_dir)])


def test_dry_run_prints_but_writes_nothing(data_dir, tmp_path, capsys):
    main([str(_source(tmp_path)), "--mode", "route", "--category", "car",
          "--data-dir", str(data_dir), "--dry-run"])

    out = capsys.readouterr().out
    assert "Ring" in out
    assert "[dry-run" in out
    assert not CountryPaths(data_dir, "AA").geo.exists()


def test_tagged_file_error_is_caught_and_exits(data_dir, tmp_path):
    invalid_source = tmp_path / "invalid.json"
    invalid_source.write_text(json.dumps({"name": "x"}), "utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main([str(invalid_source), "--mode", "route", "--category", "car",
              "--data-dir", str(data_dir)])

    assert isinstance(excinfo.value.code, str)
    assert "customCoordinates" in excinfo.value.code
