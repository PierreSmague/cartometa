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


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    """No test may pop a real notification; the calls are recorded instead."""
    sent = []
    monkeypatch.setattr(cli, "notify", lambda title, body: sent.append((title, body)))
    return sent


def _cli(paths, *args, fetch):
    cli.main(["--data-dir", str(paths.data), "--logs-dir", str(paths.data.parent / "logs"),
              *args], fetch=fetch)


def _log(paths):
    log = paths.data.parent / "logs" / "carmeta-sync.log"
    return log.read_text("utf-8").splitlines() if log.exists() else []


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
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
    _cli(paths, "sync", fetch=fake)
    assert "2 nouveau(x)" in capsys.readouterr().out

    _cli(paths, "sync", fetch=fake)
    assert capsys.readouterr().out == ""


def test_a_network_failure_exits_with_code_one(paths, capsys):
    def broken(url, headers):
        raise github.GithubError("api.github.com: unreachable")

    with pytest.raises(SystemExit) as exit_info:
        _cli(paths, "sync", fetch=broken)

    assert exit_info.value.code == 1
    assert "unreachable" in capsys.readouterr().err
    assert not paths.cache.exists()


def test_a_held_lock_is_not_a_failure(paths, fake, capsys):
    paths.lock.parent.mkdir(parents=True)
    paths.lock.write_text("123 now\n")

    _cli(paths, "sync", fetch=fake)

    assert "another sync" in capsys.readouterr().out


def test_status_summarises_the_cached_analysis(paths, fake, capsys):
    save_rules(paths.rules, _rules())
    _cli(paths, "status", fetch=fake)
    assert "Aucune analyse" in capsys.readouterr().out

    run_sync(paths, _rules(), fake)
    _cli(paths, "status", fetch=fake)

    out = capsys.readouterr().out
    assert "AA    1 retenus" in out and "Total : 2 retenus" in out


def test_a_neighbour_with_a_handful_of_points_gets_no_analysis(paths, fake):
    # 4 points of the Aa file fall in BB's territory... and BB has no file of its own.
    stray = lattice(_half("Blue 2024")) + lattice(_half("Blue 2024"), n=2, lng0=22.0)
    only = FakeGithub({MX: points_file(stray, name="Aa")})

    result = run_sync(paths, _rules(), only)

    assert result.analysed == ["AA"]
    assert [p.name for p in paths.analysis_dir.iterdir()] == ["AA.json"]


def test_a_useful_run_writes_the_report_a_log_line_and_notifies(paths, fake, capsys,
                                                               notifications):
    save_rules(paths.rules, _rules())

    _cli(paths, "sync", fetch=fake)

    out = capsys.readouterr().out
    assert "2 nouveau(x), 0 modifié(s), 0 supprimé(s) - 2 meta(s) à importer" in out
    assert paths.report.read_text("utf-8").startswith("<!doctype html>")
    (line,) = _log(paths)
    assert line.endswith("2 nouveau(x), 0 modifié(s), 0 supprimé(s) - 2 meta(s) à importer, "
                         "0 cas en attente, 0 empreinte(s) validée(s) qui ont bougé, "
                         "0 tag(s) disparu(s)")
    assert notifications == [("carmeta", "2 nouveau(x), 0 modifié(s), 0 supprimé(s). "
                              "2 meta(s) à importer, 0 cas en attente, 0 empreinte(s) "
                              "validée(s) qui ont bougé, 0 tag(s) disparu(s)")]


def test_a_run_with_nothing_new_leaves_no_trace_at_all(paths, fake, tmp_path, notifications):
    save_rules(paths.rules, _rules())
    _cli(paths, "sync", fetch=fake)
    before = _snapshot(tmp_path)
    notifications.clear()

    _cli(paths, "sync", fetch=fake)

    assert _snapshot(tmp_path) == before
    assert notifications == []


def test_a_failure_is_logged(paths):
    def broken(url, headers):
        raise github.GithubError("api.github.com: unreachable")

    with pytest.raises(SystemExit):
        _cli(paths, "sync", fetch=broken)

    (line,) = _log(paths)
    assert "ERREUR api.github.com: unreachable" in line


def test_a_notification_that_fails_does_not_fail_the_run(paths, fake, monkeypatch):
    from cartometa.carmeta import notify as notify_module

    def no_desktop(*args, **kwargs):
        raise OSError("no desktop session")

    monkeypatch.setattr(notify_module.subprocess, "run", no_desktop)
    monkeypatch.setattr(cli, "notify", notify_module.notify)
    save_rules(paths.rules, _rules())

    _cli(paths, "sync", fetch=fake)                  # no exception, exit code 0

    assert len(_log(paths)) == 1


def test_the_notification_never_puts_its_text_in_a_shell(monkeypatch):
    from cartometa.carmeta import notify as notify_module
    calls = []

    class Done:
        returncode = 0

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return Done()

    monkeypatch.setattr(notify_module.subprocess, "run", run)
    hostile = 'x" & do shell script "rm -rf ~'

    monkeypatch.setattr(notify_module.sys, "platform", "darwin")
    assert notify_module.notify("carmeta", hostile) is True
    command, kwargs = calls[-1]
    assert command[:2] == ["osascript", "-e"] and "shell" not in kwargs
    # Quoted as one AppleScript string: the quote is escaped, not closing it.
    assert '"x\\" & do shell script \\"rm -rf ~"' in command[2]

    monkeypatch.setattr(notify_module.sys, "platform", "win32")
    notify_module.notify("carmeta", hostile)
    command, kwargs = calls[-1]
    assert hostile not in " ".join(command)
    assert kwargs["env"]["CARMETA_BODY"] == hostile
