import json
import re

import pytest

from cartometa.carmeta import importer
from cartometa.carmeta.importer import run_import
from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.report import (
    build_report,
    headline,
    render_report,
    summary_lines,
    totals,
    write_report,
)
from cartometa.carmeta.sync import SyncResult
from cartometa.models import STATUS_TRACED
from tests.test_carmeta_importer import NOW, _analyse, _decide, _row, _rules


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "port_is_taken", lambda host, port: False)
    return tmp_path / "data"


def _busy_country(data):
    """One country showing every section: to import, moved, vanished, pending."""
    _analyse(data, [_row(), _row("Blue 2023", west=5.0, year=2023),
                    _row("Blue 2022", west=9.0, year=2022)])
    run_import(data, None, _rules(), now=NOW)
    _decide(data, "Blue 2024", STATUS_TRACED)          # will move
    _decide(data, "Blue 2022", STATUS_TRACED)          # will vanish
    paths = CarmetaPaths(data)
    paths.state.write_text(json.dumps({"tree_sha": "t", "checked_at": NOW, "dirty": [], "files": {
        "Zone/Aa/Aa 1.json": {"sha": "sha2", "kind": "points"},
        "Zone/Aa/old.json": {"sha": "sha0", "kind": "points"},
        "README.md": {"sha": "r", "kind": "other"},
    }}), "utf-8")
    _analyse(data, [
        _row(west=1.2),                                               # footprint moved
        _row("Blue 2023", west=5.0, year=2023),                       # same footprint, new file
        _row("Blue 2025", west=13.0, year=2025),                      # new
        _row("Blue 2021", west=17.0, year=2021, verdict="arbitrage",
             reason="discriminance limite", gain=0.17),               # borderline
        _row("Ford 2020", west=21.0, year=2020, key="Ford"),          # unknown descriptor
        _row("Blue 2019", west=25.0, year=2019, verdict="écarté",
             reason="points surtout isolés"),                         # no footprint
    ], sha="sha2")
    return paths


def test_the_report_tells_what_an_import_would_do(data):
    paths = _busy_country(data)

    report = build_report(paths, _rules(), SyncResult(changed=True, modified=["Zone/Aa/Aa 1.json"]),
                          now=NOW)

    assert report["countries"] == {"AA": {
        "retenu": 3, "arbitrage": 2, "écarté": 1, "import": 3, "moved": 1, "vanished": 1}}
    by_tag = {row["t"]: row for row in report["rows"]}
    # The dropped row has no footprint: counted above, not drawn.
    assert set(by_tag) == {"Blue 2024", "Blue 2023", "Blue 2025", "Blue 2021", "Ford 2020"}
    assert (by_tag["Blue 2024"]["act"], by_tag["Blue 2024"]["det"]) == (
        "re-proposée", "recouvrement 67%")
    # Still proposed, but its figures now come from the new version of the file.
    assert by_tag["Blue 2025"]["act"] == "écrite" and by_tag["Blue 2023"]["act"] == "réécrite"
    assert (by_tag["Blue 2021"]["v"], by_tag["Ford 2020"]["why"]) == (
        "arbitrage", "descripteur inconnu")
    assert by_tag["Blue 2025"]["title"] == "Blue car · 2025"
    assert by_tag["Blue 2025"]["sv"].startswith("https://www.google.com/maps/@?api=1")
    assert report["vanished"] == [{"cc": "AA", "title": "Blue car · 2022", "tag": "Blue 2022",
                                   "kind": "disparue, conservée",
                                   "why": "tag absent du fichier"}]
    assert report["descriptors"] == [{"key": "Ford", "tags": ["AA Ford 2020"]}]
    assert report["pending"] == 2
    assert report["unused"] == ["Zone/Aa/old.json"]
    assert report["changes"]["modified"] == ["Zone/Aa/Aa 1.json"]
    assert list(report["grids"]) == ["AA|0"]


def test_building_the_report_writes_nothing_outside_the_cache(data):
    paths = _busy_country(data)
    watched = [p for p in data.rglob("*") if p.is_file() and paths.cache not in p.parents]
    before = {p: p.read_bytes() for p in watched}

    write_report(paths, _rules())

    assert {p: p.read_bytes() for p in watched} == before
    assert paths.report.exists()


def test_status_and_report_give_the_same_counters(data):
    report = build_report(_busy_country(data), _rules(), now=NOW)

    lines = summary_lines(report)

    assert totals(report) == {"retenu": 3, "arbitrage": 2, "écarté": 1, "import": 3,
                              "moved": 1, "vanished": 1}
    assert headline(report) == ("3 meta(s) à importer, 2 cas en attente, 1 empreinte(s) "
                                "validée(s) qui ont bougé, 1 tag(s) disparu(s)")
    assert headline(report) in lines
    assert ("  AA    3 retenus    2 en arbitrage    1 écartés  3 à importer  "
            "1 empreinte(s) à revoir  1 disparu(s)") in lines
    assert any("cartometa-carmeta prune" in line for line in lines)
    assert any("cartometa-carmeta arbitrate" in line for line in lines)
    assert "Descripteurs inconnus : Ford" in lines


def test_the_page_is_self_contained(data):
    page = render_report(build_report(_busy_country(data), _rules(), now=NOW))

    template = page.split('<script type="application/json" id="data">')[0]
    assert "http://" not in template and "https://" not in template
    assert "<link" not in page and "@import" not in page and " src=" not in page
    # The only addresses in the whole page are the Street View links of the data.
    assert set(re.findall(r"https?://[a-z.]+", page)) == {"https://www.google.com"}
    embedded = page.split('id="data">')[1].split("</script>")[0]
    assert json.loads(embedded)["countries"]["AA"]["import"] == 3


def test_a_hostile_tag_cannot_break_out_of_the_page(data):
    hostile = '</script><script>alert(1)</script><!-- 2024'
    _analyse(data, [_row(hostile, key=hostile, family="unknown", year=None)])
    rules = _rules()

    page = render_report(build_report(CarmetaPaths(data), rules, now=NOW))

    assert "<script>alert(1)" not in page
    assert page.count("</script>") == 2          # the data block and the code, no more
    embedded = page.split('id="data">')[1].split("</script>")[0]
    assert json.loads(embedded)["rows"][0]["t"] == hostile


def test_the_report_survives_an_analysis_the_import_would_refuse(data):
    paths = _busy_country(data)
    changed = _rules()
    changed.thresholds.gain_keep = 0.5

    report = build_report(paths, changed, now=NOW)

    assert any("sync --force" in warning for warning in report["warnings"])
    assert len(report["rows"]) == 5 and report["vanished"] == []
    assert any(line.startswith("! ") for line in summary_lines(report))


def test_no_analysis_says_so(tmp_path):
    report = build_report(CarmetaPaths(tmp_path / "data"), _rules(), now=NOW)

    assert summary_lines(report) == [
        "Aucune analyse en cache : lancer `cartometa-carmeta sync`."]
