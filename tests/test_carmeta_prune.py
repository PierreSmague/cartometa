import pytest

from cartometa.carmeta import importer, prune
from cartometa.carmeta.importer import CarmetaImportError, run_import
from cartometa.carmeta.prune import run_prune, vanished_validated
from cartometa.carmeta.texts import meta_id
from cartometa.models import STATUS_REJECTED, STATUS_TRACED
from cartometa.review.store import CountryPaths, load_geo, load_metas
from tests.test_carmeta_importer import NOW, _analyse, _decide, _files, _row, _rules


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "port_is_taken", lambda host, port: False)
    monkeypatch.setattr(prune, "port_is_taken", lambda host, port: False)
    return tmp_path / "data"


def _published_then_gone(data):
    """`©2019` validated, then entirely re-shot: the tag is gone from the file."""
    old = _row("©2019", family="copyright", key=None, year=2019)
    _analyse(data, [old, _row()])
    run_import(data, None, _rules(), now=NOW)
    _decide(data, "©2019", STATUS_TRACED)
    _decide(data, "Blue 2024", STATUS_TRACED)
    _analyse(data, [_row()], sha="sha2")
    return meta_id("AA", "©2019")


def _run(data, answers, **kwargs):
    answers = list(answers)
    printed = []
    deleted = run_prune(data, None, _rules(), lambda prompt: answers.pop(0),
                        printed.append, **kwargs)
    return deleted, "\n".join(printed)


def test_a_vanished_validated_meta_is_listed_then_deleted(data):
    gone = _published_then_gone(data)

    (candidate,) = vanished_validated(data, None, _rules())
    assert (candidate.meta_id, candidate.detail) == (gone, "tag absent du fichier")

    deleted, printed = _run(data, ["o"])

    assert [action.meta_id for action in deleted] == [gone]
    assert "©2019 copyright  (tag absent du fichier)" in printed
    assert "1 meta(s) supprimée(s) sur 1." in printed
    paths = CountryPaths(data, "AA")
    assert [m["id"] for m in load_metas(paths)] == [meta_id("AA", "Blue 2024")]
    assert list(load_geo(paths)) == [meta_id("AA", "Blue 2024")]


def test_declining_writes_nothing(data):
    _published_then_gone(data)
    before = _files(data)

    deleted, printed = _run(data, ["n"])

    assert deleted == [] and "0 meta(s) supprimée(s) sur 1." in printed
    assert _files(data) == before


def test_yes_skips_the_question(data):
    gone = _published_then_gone(data)

    deleted, _ = _run(data, [], assume_yes=True)

    assert [action.meta_id for action in deleted] == [gone]


def test_a_tag_the_filter_now_drops_can_be_pruned_with_its_reason(data):
    _analyse(data, [_row()])
    run_import(data, None, _rules(), now=NOW)
    _decide(data, "Blue 2024", STATUS_TRACED)
    _analyse(data, [_row(verdict="écarté", reason="non discriminant", gain=0.03)], sha="sha2")

    _, printed = _run(data, ["o"])

    assert "(non discriminant)" in printed
    assert load_metas(CountryPaths(data, "AA")) == []
    assert not CountryPaths(data, "AA").carmeta_metas.exists()


def test_a_deleted_meta_is_proposed_afresh_when_its_tag_comes_back(data):
    gone = _published_then_gone(data)
    _run(data, ["o"])
    back = _row("©2019", family="copyright", key=None, year=2019)
    _analyse(data, [back, _row()], sha="sha3")

    plan = run_import(data, None, _rules(), now=NOW)

    assert {a.canonical: a.kind for a in plan.actions}["©2019"] == "écrite"
    assert load_geo(CountryPaths(data, "AA"))[gone].status == "proposé"


def test_rejected_and_still_supported_metas_are_never_offered(data):
    _analyse(data, [_row(), _row("Blue 2023", west=5.0, year=2023)])
    run_import(data, None, _rules(), now=NOW)
    _decide(data, "Blue 2024", STATUS_TRACED)          # still in the file
    _decide(data, "Blue 2023", STATUS_REJECTED)        # rejected, then gone
    _analyse(data, [_row()], sha="sha2")

    deleted, printed = _run(data, [])

    assert deleted == [] and "Aucune meta validée dont le tag a disparu." in printed


def test_a_country_without_analysis_is_never_pruned(data):
    _published_then_gone(data)
    from cartometa.carmeta.paths import CarmetaPaths
    _analyse(data, [_row()], country="BB")             # keeps the cache non-empty
    CarmetaPaths(data).analysis("AA").unlink()
    before = _files(data)

    deleted, _ = _run(data, [], assume_yes=True)

    assert deleted == [] and _files(data) == before


def test_pruning_is_refused_under_a_review_session(data, monkeypatch):
    _published_then_gone(data)
    monkeypatch.setattr(prune, "port_is_taken", lambda host, port: True)

    with pytest.raises(CarmetaImportError, match="cartometa-review"):
        _run(data, [], assume_yes=True)
