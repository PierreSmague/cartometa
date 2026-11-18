import json
import os
import time

import pytest

from cartometa.carmeta import cli, github
from cartometa.carmeta.paths import CarmetaPaths
from cartometa.carmeta.rules import LexiconEntry, Rules, save_rules
from cartometa.carmeta.sync import STALE_LOCK_SECONDS, SyncBusy, load_analyses, run_sync
from tests.carmeta_helpers import FakeGithub, lattice, points_file, write_countries

MX = "NorthAmerica/Aa/Aa 12_23_25.json"
BB = "Europe/Bb/Bb (01.02.26).json"


def _rules():
    return Rules(lexicon={"Blue": LexiconEntry("Blue car")})


def _half(tag):
    return lambda row, column: [tag] if column < 20 else []


def _aa(tag="Blue 2024"):
    return points_file(lattice(_half(tag)), name="Aa")


def _bb(tag="Blue 2023"):
    return points_file(lattice(_half(tag), lng0=22.0), name="Bb")


@pytest.fixture
def paths(tmp_path):
    data = tmp_path / "data"
    write_countries(data / "cache")
    return CarmetaPaths(data)


@pytest.fixture
def fake():
    return FakeGithub({MX: _aa(), BB: _bb(), "README.md": b"# carmeta"})


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _tags(paths, country):
    return [row["canonical"] for row in load_analyses(paths)[country]["rows"]]


def test_the_first_pass_mirrors_and_analyses_everything(paths, fake):
    result = run_sync(paths, _rules(), fake)

    assert result.changed and result.new == [BB, MX]
    assert result.analysed == ["AA", "BB"]
    assert _tags(paths, "AA") == ["Blue 2024"] and _tags(paths, "BB") == ["Blue 2023"]
    state = json.loads(paths.state.read_text("utf-8"))
    assert state["tree_sha"] == fake.tree_sha() and state["dirty"] == []
    assert state["files"][MX]["countries"] == {"AA": 1600}
    # One tree, then per data file one download and one commit date. No README.
    assert len(fake.api_calls) == 3 and len(fake.downloads) == 2
    assert json.loads(paths.pending.read_text("utf-8")) == []
    assert not paths.lock.exists()


def test_nothing_changed_is_one_call_and_not_a_byte_written(paths, fake):
    run_sync(paths, _rules(), fake)
    before = _snapshot(paths.data)
    fake.calls.clear()

    result = run_sync(paths, _rules(), fake)

    assert not result.changed
    assert len(fake.calls) == 1
    assert _snapshot(paths.data) == before


def test_sync_writes_nowhere_but_its_cache(paths, fake, tmp_path):
    save_rules(paths.rules, _rules())
    (paths.data / "geo").mkdir()
    (paths.data / "geo" / "AA.geojson").write_text("{}", "utf-8")
    outside = {name: content for name, content in _snapshot(tmp_path).items()
               if not name.startswith("data/cache/carmeta/")}

    run_sync(paths, _rules(), fake)

    after = {name: content for name, content in _snapshot(tmp_path).items()
             if not name.startswith("data/cache/carmeta/")}
    assert after == outside


def test_a_modified_file_only_redoes_its_countries(paths, fake):
    run_sync(paths, _rules(), fake)
    bb_before = paths.analysis("BB").stat().st_mtime_ns
    fake.files[MX] = _aa("Blue 2025")
    fake.calls.clear()

    result = run_sync(paths, _rules(), fake)

    assert (result.new, result.modified, result.analysed) == ([], [MX], ["AA"])
    assert _tags(paths, "AA") == ["Blue 2025"]
    assert paths.analysis("BB").stat().st_mtime_ns == bb_before
    assert len(fake.downloads) == 1
    # The previous version's compact file does not pile up.
    assert len(list(paths.files.glob("*.npz"))) == 2


def test_a_deleted_file_leaves_an_empty_analysis_not_a_missing_one(paths, fake):
    run_sync(paths, _rules(), fake)
    del fake.files[BB]

    result = run_sync(paths, _rules(), fake)

    assert result.deleted == [BB] and result.analysed == ["BB"]
    analysis = load_analyses(paths)["BB"]
    assert analysis["sources"] == [] and analysis["rows"] == []
    assert BB not in json.loads(paths.state.read_text("utf-8"))["files"]


def test_a_spent_quota_resumes_without_downloading_again(paths, fake):
    fake.fail_after = 3            # tree, first commit date, its download
    with pytest.raises(github.RateLimited):
        run_sync(paths, _rules(), fake)
    assert not paths.lock.exists()
    state = json.loads(paths.state.read_text("utf-8"))
    assert list(state["files"]) == [BB] and state["dirty"] == ["BB"]
    assert not paths.analysis_dir.exists()

    fake.fail_after = None
    fake.calls.clear()
    result = run_sync(paths, _rules(), fake)

    assert [u for u in fake.downloads if "Bb" in u] == []
    assert len(fake.downloads) == 1
    assert result.analysed == ["AA", "BB"]


def test_an_interrupted_analysis_is_redone_without_any_download(paths, fake):
    run_sync(paths, _rules(), fake)
    state = json.loads(paths.state.read_text("utf-8"))
    state["dirty"] = ["AA"]                      # as a crash before the analysis leaves it
    paths.state.write_text(json.dumps(state), "utf-8")
    paths.analysis("AA").unlink()
    fake.calls.clear()

    result = run_sync(paths, _rules(), fake)

    assert result.analysed == ["AA"] and len(fake.calls) == 1
    assert _tags(paths, "AA") == ["Blue 2024"]


def test_force_redoes_every_analysis_with_the_new_rules(paths, fake):
    run_sync(paths, _rules(), fake)
    fake.calls.clear()
    strict = _rules()
    strict.thresholds.gain_keep = 0.99

    result = run_sync(paths, strict, fake, force=True)

    assert result.analysed == ["AA", "BB"] and len(fake.calls) == 1
    assert load_analyses(paths)["AA"]["rows"][0]["verdict"] == "arbitrage"
    assert json.loads(paths.pending.read_text("utf-8"))[0]["key"] == "AA|Blue 2024"


def test_a_file_committed_during_the_run_waits_for_the_next_one(paths, fake):
    real = fake.__call__

    def racing(url, headers):
        if url.startswith(github.RAW) and "Aa" in url:
            return _aa("Blue 2030")              # not what the tree announced
        return real(url, headers)

    result = run_sync(paths, _rules(), racing)

    assert result.postponed == [MX] and result.analysed == ["BB"]
    assert json.loads(paths.state.read_text("utf-8"))["tree_sha"] is None

    result = run_sync(paths, _rules(), fake)
    assert result.new == [MX] and _tags(paths, "AA") == ["Blue 2024"]


def test_two_syncs_cannot_run_together(paths, fake):
    paths.lock.parent.mkdir(parents=True)
    paths.lock.write_text("123 now\n")

    with pytest.raises(SyncBusy):
        run_sync(paths, _rules(), fake)
    assert paths.lock.exists()


def test_a_stale_lock_is_taken_over(paths, fake):
    paths.lock.parent.mkdir(parents=True)
    paths.lock.write_text("123 long ago\n")
    old = time.time() - STALE_LOCK_SECONDS - 60
    os.utime(paths.lock, (old, old))

    assert run_sync(paths, _rules(), fake).changed
    assert not paths.lock.exists()


def test_the_command_is_silent_when_nothing_changed(paths, fake, capsys):
    cli.main(["--data-dir", str(paths.data), "sync"], fetch=fake)
    assert "2 nouveau(x)" in capsys.readouterr().out

    cli.main(["--data-dir", str(paths.data), "sync"], fetch=fake)
    assert capsys.readouterr().out == ""


def test_a_network_failure_exits_with_code_one(paths, capsys):
    def broken(url, headers):
        raise github.GithubError("api.github.com: unreachable")

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--data-dir", str(paths.data), "sync"], fetch=broken)

    assert exit_info.value.code == 1
    assert "unreachable" in capsys.readouterr().err
    assert not paths.cache.exists()


def test_a_held_lock_is_not_a_failure(paths, fake, capsys):
    paths.lock.parent.mkdir(parents=True)
    paths.lock.write_text("123 now\n")

    cli.main(["--data-dir", str(paths.data), "sync"], fetch=fake)

    assert "another sync" in capsys.readouterr().out


def test_status_summarises_the_cached_analysis(paths, fake, capsys):
    save_rules(paths.rules, _rules())
    cli.main(["--data-dir", str(paths.data), "status"], fetch=fake)
    assert "Aucune analyse" in capsys.readouterr().out

    run_sync(paths, _rules(), fake)
    cli.main(["--data-dir", str(paths.data), "status"], fetch=fake)

    out = capsys.readouterr().out
    assert "AA    1 retenus" in out and "Total : 2 retenus" in out


def test_a_neighbour_with_a_handful_of_points_gets_no_analysis(paths, fake):
    # 4 points of the Aa file fall in BB's territory... and BB has no file of its own.
    stray = lattice(_half("Blue 2024")) + lattice(_half("Blue 2024"), n=2, lng0=22.0)
    only = FakeGithub({MX: points_file(stray, name="Aa")})

    result = run_sync(paths, _rules(), only)

    assert result.analysed == ["AA"]
    assert [p.name for p in paths.analysis_dir.iterdir()] == ["AA.json"]
