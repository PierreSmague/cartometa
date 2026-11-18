import json

import pytest
from shapely.geometry import shape

from cartometa.carmeta import importer
from cartometa.carmeta.importer import (
    CarmetaImportError,
    plan_import,
    run_import,
)
from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.rules import Decision, LexiconEntry, Rules, analysis_fingerprint
from cartometa.carmeta.texts import meta_id
from cartometa.models import (
    STATUS_PROPOSED,
    STATUS_REJECTED,
    STATUS_TRACED,
    GeoRecord,
)
from cartometa.review.store import CountryPaths, build_queue, load_geo, load_metas, save_geo

NOW = "2026-11-18T10:00:00+00:00"


def _rules():
    return Rules(lexicon={"Blue": LexiconEntry("Blue car"),
                          "Ford": LexiconEntry("Ford", "pending")})


def _square(west, south=1.0, side=1.0):
    return [{"kind": "polygon", "ring": [[west, south], [west + side, south],
                                         [west + side, south + side], [west, south + side]]},
            {"kind": "clip"}]


def _row(canonical="Blue 2024", west=1.0, side=1.0, verdict="retenu", reason="",
         gain=0.42, key="Blue", family="car_year", year=2024, points=13750):
    kept = verdict != "écarté" or reason == "non discriminant"
    return {"canonical": canonical, "family": family, "lexicon_key": key, "year": year,
            "antenna": None, "raw_tags": [canonical], "color": "#3366cc", "source": 0,
            "points": points, "zones": 45, "capture": 0.9, "gain": gain,
            "verdict": verdict, "reason": reason,
            "rep": {"lat": 1.5, "lng": west + 0.5, "pano": "PANO", "heading": 271.5},
            "pieces": _square(west, side=side) if kept else None, "cells": "AA=="}


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "port_is_taken", lambda host, port: False)
    return tmp_path / "data"


def _analyse(data, rows, country="AA", rules=None, path="Zone/Aa/Aa 1.json", sha="sha1"):
    paths = CarmetaPaths(data)
    paths.analysis_dir.mkdir(parents=True, exist_ok=True)
    paths.analysis(country).write_text(json.dumps({
        "country": country,
        "rules_fingerprint": analysis_fingerprint(rules or _rules()),
        "sources": [{"path": path, "sha": sha, "date": "2026-05-06T13:05:16Z",
                     "role": "primary", "points": 150000, "families": ["car_year"],
                     "grid": {"s": 1.5, "W": 4, "H": 2, "D": 40.0, "R": 4.0,
                              "delta": 1.0, "link": 3.0, "cov": "8A=="}}],
        "rows": rows,
    }), "utf-8")


def _files(data, country="AA"):
    paths = CountryPaths(data, country)
    return tuple(p.read_bytes() if p.exists() else None
                 for p in (paths.carmeta_metas, paths.geo))


def _kinds(plan):
    return {action.canonical: action.kind for action in plan.actions}


def _decide(data, canonical, status, country="AA", pieces=None):
    """What the review does on A or R."""
    paths = CountryPaths(data, country)
    records = load_geo(paths)
    identifier = meta_id(country, canonical)
    pieces = pieces if pieces is not None else records[identifier].pieces
    geometry = None
    if status == STATUS_TRACED:
        ring = pieces[0]["ring"]
        geometry = {"type": "Polygon", "coordinates": [ring + [ring[0]]]}
    records[identifier] = GeoRecord(id=identifier, geometry=geometry,
                                    pieces=pieces if status == STATUS_TRACED else [],
                                    status=status)
    save_geo(paths, records)
    return identifier


def test_a_retained_tag_becomes_a_proposed_meta(data):
    _analyse(data, [_row()])

    plan = run_import(data, None, _rules(), now=NOW)

    assert _kinds(plan) == {"Blue 2024": "écrite"}
    identifier = meta_id("AA", "Blue 2024")
    (meta,) = load_metas(CountryPaths(data, "AA"))
    assert meta == {
        "id": identifier, "country": "AA", "tier": "manual", "origin": "carmeta",
        "category": "car", "title": "Blue car · 2024",
        "description": "Street View coverage from 2024 shot with the blue car. "
                       "Footprint computed from 13,750 locations tagged by carmeta.",
        "description_origin": "generated",
        "source_url": "https://github.com/iggedi-ig-ig/carmeta",
        "extracted_at": NOW, "image": None,
        "maps_url": "https://www.google.com/maps/@?api=1&map_action=pano&pano=PANO"
                    "&viewpoint=1.5%2C1.5&heading=271.5&pitch=-35",
        "maps_latlon": [1.5, 1.5],
        "carmeta": {
            "canonical": "Blue 2024", "family": "car_year", "raw_tags": ["Blue 2024"],
            "source_path": "Zone/Aa/Aa 1.json", "source_sha": "sha1",
            "source_date": "2026-05-06", "points": 13750, "zones": 45,
            "capture": 0.9, "gain": 0.42, "color": "#3366cc",
            "baseline": {"type": "MultiPolygon", "coordinates": [[[
                [1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 2.0], [1.0, 1.0]]]]},
        },
    }
    record = load_geo(CountryPaths(data, "AA"))[identifier]
    assert record.status == STATUS_PROPOSED and record.pieces == _square(1.0)
    (item,) = build_queue(CountryPaths(data, "AA"))["items"]
    assert item["status"] == STATUS_PROPOSED and item["latlon"] == [1.5, 1.5]


def test_a_second_identical_import_writes_nothing(data):
    _analyse(data, [_row(), _row("Blue 2023", west=5.0, year=2023)])
    run_import(data, None, _rules(), now=NOW)
    before = _files(data)
    stamps = [p.stat().st_mtime_ns for p in (CountryPaths(data, "AA").carmeta_metas,
                                             CountryPaths(data, "AA").geo)]

    plan = run_import(data, None, _rules(), now="2027-01-01T00:00:00+00:00")

    assert set(_kinds(plan).values()) == {"inchangée"}
    assert _files(data) == before
    assert [p.stat().st_mtime_ns for p in (CountryPaths(data, "AA").carmeta_metas,
                                           CountryPaths(data, "AA").geo)] == stamps


def test_a_proposed_meta_is_rewritten_with_the_new_footprint(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    _analyse(data, [_row(west=1.5, points=14000)], sha="sha2")

    plan = run_import(data, None, _rules(), now="2027-01-01T00:00:00+00:00")

    assert _kinds(plan) == {"Blue 2024": "réécrite"}
    paths = CountryPaths(data, "AA")
    (meta,) = load_metas(paths)
    assert meta["extracted_at"] == NOW                  # kept across runs
    assert meta["carmeta"]["source_sha"] == "sha2" and "14,000" in meta["description"]
    record = load_geo(paths)[meta["id"]]
    assert record.status == STATUS_PROPOSED and record.pieces == _square(1.5)


def test_a_rejection_is_final(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    _decide(data, "Blue 2024", STATUS_REJECTED)
    before = _files(data)
    _analyse(data, [_row(west=7.0)], sha="sha2")

    plan = run_import(data, None, _rules(), now=NOW)

    assert _kinds(plan) == {"Blue 2024": "rejetée, jamais re-proposée"}
    assert _files(data) == before


def test_a_validated_meta_whose_footprint_barely_moved_is_left_alone(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    _decide(data, "Blue 2024", STATUS_TRACED)
    before = _files(data)
    # Shifted by 0.08: intersection 0.92, union 1.08 — 85 % overlap.
    _analyse(data, [_row(west=1.08, points=20000)], sha="sha2")

    plan = run_import(data, None, _rules(), now=NOW)

    (action,) = plan.actions
    assert action.kind == "validée, empreinte stable" and action.detail == "recouvrement 85%"
    assert _files(data) == before


def test_a_validated_meta_whose_footprint_moved_gets_a_proposal_and_stays_published(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    identifier = _decide(data, "Blue 2024", STATUS_TRACED)
    validated = load_geo(CountryPaths(data, "AA"))[identifier]
    # Shifted by 0.2: intersection 0.8, union 1.2 — 67 % overlap.
    _analyse(data, [_row(west=1.2, points=20000)], sha="sha2")

    plan = run_import(data, None, _rules(), now=NOW)

    (action,) = plan.actions
    assert action.kind == "re-proposée" and action.detail == "recouvrement 67%"
    record = load_geo(CountryPaths(data, "AA"))[identifier]
    assert record.status == STATUS_TRACED
    assert record.geometry == validated.geometry and record.pieces == validated.pieces
    assert record.proposal == {"pieces": _square(1.2)}
    (meta,) = load_metas(CountryPaths(data, "AA"))
    assert shape(meta["carmeta"]["baseline"]).bounds == (1.2, 1.0, 2.2, 2.0)
    assert meta["carmeta"]["points"] == 20000


def test_a_dismissed_reproposal_does_not_come_back(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    identifier = _decide(data, "Blue 2024", STATUS_TRACED)
    _analyse(data, [_row(west=1.2)], sha="sha2")
    run_import(data, None, _rules(), now=NOW)
    # R in the review: the proposal goes, the validated footprint stays.
    paths = CountryPaths(data, "AA")
    records = load_geo(paths)
    records[identifier].proposal = None
    save_geo(paths, records)
    before = _files(data)

    plan = run_import(data, None, _rules(), now=NOW)

    assert _kinds(plan) == {"Blue 2024": "validée, empreinte stable"}
    assert _files(data) == before


def test_a_hand_retouched_footprint_is_not_compared_with_the_computed_one(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    # The maintainer validated something quite different from the proposal.
    _decide(data, "Blue 2024", STATUS_TRACED, pieces=_square(1.0, side=3.0)[:1])
    before = _files(data)

    plan = run_import(data, None, _rules(), now=NOW)

    assert _kinds(plan) == {"Blue 2024": "validée, empreinte stable"}
    assert _files(data) == before


def test_a_label_corrected_in_the_lexicon_reaches_a_validated_meta(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    identifier = _decide(data, "Blue 2024", STATUS_TRACED)
    geo_before = CountryPaths(data, "AA").geo.read_bytes()
    _analyse(data, [_row(points=99999)], sha="sha2")     # new file, same footprint
    corrected = _rules()
    corrected.lexicon["Blue"] = LexiconEntry("Blue Google car")

    plan = run_import(data, None, corrected, now=NOW)

    assert _kinds(plan) == {"Blue 2024": "texte mis à jour"}
    (meta,) = load_metas(CountryPaths(data, "AA"))
    assert meta["title"] == "Blue Google car · 2024"
    # The stored figures did not move: only the wording did.
    assert "13,750" in meta["description"] and meta["carmeta"]["source_sha"] == "sha1"
    assert CountryPaths(data, "AA").geo.read_bytes() == geo_before
    assert load_geo(CountryPaths(data, "AA"))[identifier].status == STATUS_TRACED


def test_a_vanished_tag_keeps_its_validated_meta_and_loses_its_proposed_one(data):
    _analyse(data, [_row(), _row("Blue 2023", west=5.0, year=2023)])
    run_import(data, None, _rules(), now=NOW)
    kept = _decide(data, "Blue 2024", STATUS_TRACED)
    gone = meta_id("AA", "Blue 2023")
    _analyse(data, [_row("Blue 2025", west=9.0, year=2025)], sha="sha2")

    plan = run_import(data, None, _rules(), now=NOW)

    assert _kinds(plan) == {"Blue 2025": "écrite", "Blue 2024": "disparue, conservée",
                            "Blue 2023": "disparue, supprimée"}
    assert {a.canonical: a.detail for a in plan.actions if "disparue" in a.kind} == {
        "Blue 2024": "tag absent du fichier", "Blue 2023": "tag absent du fichier"}
    paths = CountryPaths(data, "AA")
    assert {m["id"] for m in load_metas(paths)} == {kept, meta_id("AA", "Blue 2025")}
    records = load_geo(paths)
    assert gone not in records and records[kept].status == STATUS_TRACED


def test_a_tag_the_filter_now_drops_is_vanished_too(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    _analyse(data, [_row(verdict="écarté", reason="non discriminant", gain=0.03)], sha="sha2")

    plan = run_import(data, None, _rules(), now=NOW)

    (action,) = plan.actions
    assert (action.kind, action.detail) == ("disparue, supprimée", "non discriminant")
    assert _files(data) == (None, CountryPaths(data, "AA").geo.read_bytes())
    assert load_geo(CountryPaths(data, "AA")) == {}


def test_a_vanished_rejected_meta_keeps_its_rejection(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    _decide(data, "Blue 2024", STATUS_REJECTED)
    before = _files(data)
    _analyse(data, [], sha="sha2")

    plan = run_import(data, None, _rules(), now=NOW)
    assert plan.actions == [] and _files(data) == before

    # …so that it is still rejected the day the tag comes back.
    _analyse(data, [_row()], sha="sha3")
    assert _kinds(run_import(data, None, _rules(), now=NOW)) == {
        "Blue 2024": "rejetée, jamais re-proposée"}


def test_a_vanished_validated_meta_loses_its_pending_proposal(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    identifier = _decide(data, "Blue 2024", STATUS_TRACED)
    _analyse(data, [_row(west=1.2)], sha="sha2")
    run_import(data, None, _rules(), now=NOW)
    _analyse(data, [], sha="sha3")

    plan = run_import(data, None, _rules(), now=NOW)

    assert _kinds(plan) == {"Blue 2024": "disparue, conservée"}
    record = load_geo(CountryPaths(data, "AA"))[identifier]
    assert record.status == STATUS_TRACED and record.proposal is None


def test_tags_awaiting_arbitration_are_left_aside_and_counted(data):
    _analyse(data, [
        _row(),
        _row("Blue 2023", west=5.0, year=2023, verdict="arbitrage",
             reason="discriminance limite", gain=0.17),
        _row("Ford 2022", west=9.0, year=2022, key="Ford"),
    ])

    plan = run_import(data, None, _rules(), now=NOW)

    assert _kinds(plan) == {"Blue 2024": "écrite"}
    assert plan.countries[0].waiting == 2

    decided = _rules()
    decided.decisions["AA|Blue 2023"] = Decision("keep", 0.17, "2026-11-20")
    decided.lexicon["Ford"] = LexiconEntry("Ford")
    assert _kinds(run_import(data, None, decided, now=NOW)) == {
        "Blue 2024": "inchangée", "Blue 2023": "écrite", "Ford 2022": "écrite"}


def test_a_meta_whose_decision_went_stale_is_neither_updated_nor_deleted(data):
    rules = _rules()
    rules.decisions["AA|Blue 2024"] = Decision("keep", 0.17, "2026-11-20")
    _analyse(data, [_row(verdict="arbitrage", reason="discriminance limite", gain=0.17)])
    run_import(data, None, rules, now=NOW)
    before = _files(data)
    _analyse(data, [_row(gain=0.40)], sha="sha2")        # moved by 23 points

    plan = run_import(data, None, rules, now=NOW)

    assert _kinds(plan) == {"Blue 2024": "en attente d'arbitrage, conservée"}
    assert _files(data) == before


def test_a_new_version_of_a_file_creates_no_duplicate(data):
    _analyse(data, [_row("Blue 2024")], path="Zone/Aa/Aa 1.json", sha="sha1")
    run_import(data, None, _rules(), now=NOW)
    # Renamed file, and the tag spelled another way: same canonical form.
    renamed = _row("Blue 2024")
    renamed["raw_tags"] = ["Blue Car 24"]
    _analyse(data, [renamed], path="Zone/Aa/Aa 2 (new).json", sha="sha2")

    plan = run_import(data, None, _rules(), now=NOW)

    assert _kinds(plan) == {"Blue 2024": "réécrite"}
    assert len(load_metas(CountryPaths(data, "AA"))) == 1
    assert len(load_geo(CountryPaths(data, "AA"))) == 1


def test_dry_run_writes_nothing(data):
    _analyse(data, [_row()])

    plan = run_import(data, None, _rules(), dry_run=True, now=NOW)

    assert _kinds(plan) == {"Blue 2024": "écrite"}
    assert _files(data) == (None, None)
    assert not (data / "carmeta").exists() and not (data / "geo").exists()


def test_the_import_refuses_to_run_under_a_review_session(data, monkeypatch):
    _analyse(data, [_row()])
    monkeypatch.setattr(importer, "port_is_taken", lambda host, port: True)

    with pytest.raises(CarmetaImportError, match="cartometa-review"):
        run_import(data, None, _rules(), now=NOW)
    assert _files(data) == (None, None)
    # A dry run reads only: the review may stay open.
    assert run_import(data, None, _rules(), dry_run=True, now=NOW).actions


def test_no_cached_analysis_no_import(data):
    with pytest.raises(CarmetaImportError, match="sync"):
        run_import(data, None, _rules(), now=NOW)


def test_an_analysis_made_under_other_thresholds_is_refused(data):
    _analyse(data, [_row()])
    changed = _rules()
    changed.thresholds.gain_keep = 0.5

    with pytest.raises(CarmetaImportError, match="sync --force"):
        run_import(data, None, changed, now=NOW)
    assert _files(data) == (None, None)


def test_a_country_without_analysis_is_skipped_never_purged(data):
    _analyse(data, [_row()])
    _analyse(data, [_row()], country="BB")
    run_import(data, None, _rules(), now=NOW)
    CarmetaPaths(data).analysis("BB").unlink()           # a partly wiped cache
    before = _files(data, "BB")

    plan = run_import(data, None, _rules(), now=NOW)

    assert [c.country for c in plan.countries] == ["AA"]
    assert plan.warnings == [
        "BB : aucune analyse en cache, pays ignoré (ses metas carmeta sont conservées)"]
    assert _files(data, "BB") == before


def test_only_the_requested_countries_are_imported(data):
    _analyse(data, [_row()])
    _analyse(data, [_row()], country="BB")

    plan = run_import(data, ["bb"], _rules(), now=NOW)

    assert [c.country for c in plan.countries] == ["BB"]
    assert _files(data, "AA") == (None, None)


def test_two_tags_giving_the_same_id_fail_frankly(data, monkeypatch):
    _analyse(data, [_row(), _row("Blue 2023", west=5.0, year=2023)])
    monkeypatch.setattr(importer, "meta_id", lambda country, canonical: "car-000000")

    with pytest.raises(CarmetaImportError, match="collision"):
        run_import(data, None, _rules(), now=NOW)
    assert _files(data) == (None, None)


def test_the_summary_lists_the_car_metas_already_published(data):
    _analyse(data, [_row()])
    paths = CountryPaths(data, "AA")
    paths.manual_metas.parent.mkdir(parents=True)
    paths.manual_metas.write_text(json.dumps([
        {"id": "man-1a2b", "country": "AA", "tier": "manual", "origin": "manual",
         "title": "Blue car 2024", "description": "d", "category": "car",
         "source_url": "", "extracted_at": NOW},
        {"id": "man-ffff", "country": "AA", "tier": "manual", "origin": "manual",
         "title": "A bollard", "description": "d", "category": "infrastructure",
         "source_url": "", "extracted_at": NOW},
        {"id": "man-0000", "country": "AA", "tier": "manual", "origin": "manual",
         "title": "Drawn but recategorised", "description": "d", "category": "autre",
         "source_url": "", "extracted_at": NOW},
    ]), "utf-8")
    box = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    save_geo(paths, {i: GeoRecord(id=i, geometry=box, pieces=[], status=STATUS_TRACED)
                     for i in ("man-1a2b", "man-ffff", "man-0000")})
    (data / "categories.json").write_text(json.dumps({"AA": {"man-0000": "car"}}), "utf-8")

    plan = plan_import(data, None, _rules(), now=NOW)

    assert plan.countries[0].published == [
        ("man-1a2b", "manual", "Blue car 2024"),
        ("man-0000", "manual", "Drawn but recategorised")]


def test_the_command_prints_what_it_did_and_counts_the_rest(data, tmp_path, capsys):
    from cartometa.carmeta import cli
    from cartometa.carmeta.rules import save_rules

    save_rules(CarmetaPaths(data).rules, _rules())
    _analyse(data, [_row(), _row("Blue 2023", west=5.0, year=2023, verdict="arbitrage",
                                 reason="discriminance limite", gain=0.17)])

    cli.main(["--data-dir", str(data), "import", "--dry-run"])
    out = capsys.readouterr().out
    assert "[dry-run : rien n'est écrit]" in out and _files(data) == (None, None)

    cli.main(["--data-dir", str(data), "import", "AA"])
    out = capsys.readouterr().out
    assert f"{meta_id('AA', 'Blue 2024')}  Blue car · 2024" in out and "écrite" in out
    assert "1 tag(s) en attente d'arbitrage" in out

    cli.main(["--data-dir", str(data), "import"])
    assert "1 meta(s) : inchangée" in capsys.readouterr().out


def test_the_command_fails_with_a_message_not_a_traceback(data, capsys):
    from cartometa.carmeta import cli

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--data-dir", str(data), "import"])

    assert exit_info.value.code == 1
    assert "cartometa-carmeta sync" in capsys.readouterr().err


def test_the_metas_file_holds_one_meta_per_line(data):
    _analyse(data, [_row(), _row("Blue 2023", west=5.0, year=2023)])
    run_import(data, None, _rules(), now=NOW)

    lines = CountryPaths(data, "AA").carmeta_metas.read_text("utf-8").splitlines()

    assert lines[0] == "[" and lines[-1] == "]" and len(lines) == 4
    assert json.loads(lines[1].rstrip(","))["title"] == "Blue car · 2023"


def test_the_baseline_is_a_coarse_summary_yet_compares_exactly(data):
    from shapely.geometry import Point

    # A footprint with hundreds of vertices, as real ones have.
    disc = Point(5.0, 5.0).buffer(1.0, quad_segs=64)
    row = _row()
    row["pieces"] = [{"kind": "polygon", "ring": [list(c) for c in disc.exterior.coords[:-1]]},
                     {"kind": "clip"}]
    _analyse(data, [row])
    run_import(data, None, _rules(), now=NOW)

    (meta,) = load_metas(CountryPaths(data, "AA"))
    baseline = meta["carmeta"]["baseline"]["coordinates"][0][0]
    assert len(baseline) < len(row["pieces"][0]["ring"]) / 3
    assert all(round(v, 3) == v for vertex in baseline for v in vertex)
    # Coarse as it is, the same footprint computed again overlaps it at 100 %.
    _decide(data, "Blue 2024", STATUS_TRACED)
    (action,) = run_import(data, None, _rules(), now=NOW).actions
    assert (action.kind, action.detail) == ("validée, empreinte stable", "recouvrement 100%")
