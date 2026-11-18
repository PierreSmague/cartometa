import pytest
from shapely.geometry import shape

from cartometa.carmeta import accept, importer
from cartometa.carmeta.accept import run_accept
from cartometa.carmeta.importer import CarmetaImportError, run_import
from cartometa.carmeta.texts import meta_id
from cartometa.models import STATUS_PROPOSED, STATUS_REJECTED, STATUS_TRACED, GeoRecord
from cartometa.review.store import CountryPaths, build_queue, load_geo, save_geo
from tests.carmeta_helpers import write_countries
from tests.test_carmeta_importer import NOW, _analyse, _decide, _files, _row, _rules


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "port_is_taken", lambda host, port: False)
    monkeypatch.setattr(accept, "port_is_taken", lambda host, port: False)
    data = tmp_path / "data"
    # AA spans 0–10° of longitude: a footprint at west=9.5 straddles its border.
    write_countries(data / "cache")
    return data


def test_every_proposal_is_validated_as_the_review_would(data):
    _analyse(data, [_row(), _row("Blue 2023", west=9.5, year=2023)])
    run_import(data, None, _rules(), now=NOW)

    result = run_accept(data, None)

    assert [title for _, _, title in result.accepted] == ["Blue car · 2023", "Blue car · 2024"]
    records = load_geo(CountryPaths(data, "AA"))
    inside = records[meta_id("AA", "Blue 2024")]
    assert inside.status == STATUS_TRACED and inside.proposal is None
    assert shape(inside.geometry).bounds == (1.0, 1.0, 2.0, 2.0)
    # The pieces are kept, clip included: the meta can be reopened and retouched.
    assert [p["kind"] for p in inside.pieces] == ["polygon", "clip"]
    # Clipped to the borders, like `A` after `F`: the country ends at 10°.
    assert shape(records[meta_id("AA", "Blue 2023")].geometry).bounds == (9.5, 1.0, 10.0, 2.0)
    assert build_queue(CountryPaths(data, "AA"))["items"] == []


def test_accepting_twice_changes_nothing(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    run_accept(data, None)
    before = _files(data)

    result = run_accept(data, None)

    assert (result.accepted, result.adopted, result.failed) == ([], [], [])
    assert _files(data) == before
    # …and the file was already in its settled form: a plain re-save is a no-op.
    save_geo(CountryPaths(data, "AA"), load_geo(CountryPaths(data, "AA")))
    assert _files(data) == before


def test_a_pending_reproposal_is_adopted(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    identifier = _decide(data, "Blue 2024", STATUS_TRACED)
    _analyse(data, [_row(west=1.2)], sha="sha2")
    run_import(data, None, _rules(), now=NOW)

    result = run_accept(data, None)

    assert [i for _, i, _ in result.adopted] == [identifier] and result.accepted == []
    record = load_geo(CountryPaths(data, "AA"))[identifier]
    assert record.proposal is None and shape(record.geometry).bounds == (1.2, 1.0, 2.2, 2.0)
    # The import then sees a stable footprint: nothing comes back.
    assert {a.kind for a in run_import(data, None, _rules(), now=NOW).actions} == {
        "validée, empreinte stable"}


def test_rejected_metas_and_other_proposals_are_left_alone(data):
    _analyse(data, [_row(), _row("Blue 2023", west=5.0, year=2023)])
    run_import(data, None, _rules(), now=NOW)
    rejected = _decide(data, "Blue 2023", STATUS_REJECTED)
    paths = CountryPaths(data, "AA")
    records = load_geo(paths)
    # A proposal from cartometa-import-tagged: not carmeta's to accept.
    records["tag-abcdef"] = GeoRecord(id="tag-abcdef", geometry=None, status=STATUS_PROPOSED,
                                      pieces=[{"kind": "rect", "bounds": [1, 1, 2, 2]}])
    save_geo(paths, records)

    result = run_accept(data, None)

    assert len(result.accepted) == 1
    records = load_geo(paths)
    assert records[rejected].status == STATUS_REJECTED
    assert records["tag-abcdef"].status == STATUS_PROPOSED


def test_a_footprint_entirely_outside_the_country_is_reported_not_validated(data):
    _analyse(data, [_row(), _row("Blue 2023", west=14.0, year=2023)])
    run_import(data, None, _rules(), now=NOW)

    result = run_accept(data, None)

    assert len(result.accepted) == 1
    ((country, identifier, title, reason),) = result.failed
    assert (country, title) == ("AA", "Blue car · 2023") and "outside the country" in reason
    assert load_geo(CountryPaths(data, "AA"))[identifier].status == STATUS_PROPOSED


def test_only_the_requested_countries_are_accepted(data):
    _analyse(data, [_row()])
    _analyse(data, [_row(west=21.0)], country="BB")
    run_import(data, None, _rules(), now=NOW)
    lines = []

    result = run_accept(data, ["bb"], lines.append)

    assert [country for country, _, _ in result.accepted] == ["BB"]
    assert lines == ["BB  1 meta(s) validée(s)"]
    assert load_geo(CountryPaths(data, "AA"))[meta_id("AA", "Blue 2024")].status == STATUS_PROPOSED


def test_accepting_is_refused_under_a_review_session(data, monkeypatch):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    before = _files(data)
    monkeypatch.setattr(accept, "port_is_taken", lambda host, port: True)

    with pytest.raises(CarmetaImportError, match="cartometa-review"):
        run_accept(data, None)
    assert _files(data) == before


def test_the_command_summarises(data, capsys):
    from cartometa.carmeta import cli

    _analyse(data, [_row(), _row("Blue 2023", west=14.0, year=2023)])
    run_import(data, None, _rules(), now=NOW)

    cli.main(["--data-dir", str(data), "accept"])

    out = capsys.readouterr().out
    assert "AA  1 meta(s) validée(s)" in out and "! AA" in out
    assert "1 proposition(s) validée(s), 0 re-proposition(s) adoptée(s), 1 laissée(s) en l'état." in out
