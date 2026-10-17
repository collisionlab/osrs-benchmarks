import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from osrs_benchmarks import checkout, cli, clickhouse, compare, machine, run, suite


INDEX = {
    "canonical": [{"name": "a/early", "tiers": ["smoke", "standard"]}, {"name": "b/early", "tiers": ["standard"]}],
    "routing-issues": [{"name": "issue 1", "tiers": []}],
}


def test_every_suite_loads():
    for name in suite.names():
        loaded = suite.load(name)
        assert loaded.backends and loaded.repetitions >= 1


def test_selectors_pick_suites_and_tiers():
    assert suite.select([{"suite": "*"}], INDEX) == [("canonical", "a/early"), ("canonical", "b/early"),
                                                     ("routing-issues", "issue 1")]
    assert suite.select([{"suite": "canonical", "tier": "smoke"}], INDEX) == [("canonical", "a/early")]
    with pytest.raises(SystemExit, match="no scenario suite"):
        suite.select([{"suite": "missing"}], INDEX)


def test_manifest_interleaves_repetitions():
    everything = suite.load("all")
    cases = suite.select(everything.scenarios, INDEX)
    manifest = suite.manifest(everything, "astar", cases, [("canonical", "a/early")])
    assert manifest["format_version"] == 2 and manifest["algorithm"] == "astar"
    assert manifest["warmup"] == [{"suite": "canonical", "scenario": "a/early"}]
    repetitions = [c["repetition"] for c in manifest["cases"]]
    assert repetitions == sorted(repetitions)
    assert len(manifest["cases"]) == len(cases) * everything.repetitions


def test_suite_hash_tracks_its_definition(tmp_path):
    raw = json.loads((suite.SUITES / "smoke.json").read_text())
    path = tmp_path / "custom.json"
    path.write_text(json.dumps(raw))
    assert suite.load(path).sha256 == suite.load("smoke").sha256
    raw["repetitions"] = 2
    path.write_text(json.dumps(raw))
    assert suite.load(path).sha256 != suite.load("smoke").sha256


def test_wait_quiet_needs_consecutive_quiet_minutes():
    samples = iter([0.2, 3.0, 0.1, 0.1, 0.1])
    machine.wait_quiet(1.0, 3, 5, sample=lambda _: next(samples), log=lambda _: None)
    with pytest.raises(machine.Busy, match="3.0 cores"):
        samples = iter([0.2, 3.0, 0.1, 0.1, 0.1])
        machine.wait_quiet(1.0, 4, 5, sample=lambda _: next(samples), log=lambda _: None)


def test_migrations_split_into_statements():
    found = clickhouse.migrations()
    assert [v for v, *_ in found] == sorted({v for v, *_ in found})
    version, name, statements = found[0]
    assert (version, name) == (1, "initial")
    assert all(s.startswith("CREATE TABLE IF NOT EXISTS benchmarks.") for s in statements)
    assert len(statements) == 4
    assert found[1][:2] == (2, "scenarios")


def write_run(directory, times, costs=None):
    """A run directory with one observation per (backend, route) at the given total_ns."""
    directory.mkdir()
    rows = []
    for (backend, scenario), ns in times.items():
        rows.append({"backend": backend, "scenario_suite": "canonical", "scenario": scenario, "repetition": 0,
                     "outcome": "ok", "path_cost": (costs or {}).get(scenario, 10), "total_ns": ns})
    record = {"run": {"run_id": directory.name, "tooling_commit": "t" * 40, "plugin_commit": "p" * 40,
                      "suite": "smoke", "runner": "test", "suite_sha256": "x"}, "executions": []}
    (directory / "run.json").write_text(json.dumps(record))
    (directory / "observations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return directory


def test_compare_reports_speed_and_result_changes(tmp_path):
    base = write_run(tmp_path / "base", {("astar", "a"): 100, ("astar", "b"): 100})
    cand = write_run(tmp_path / "cand", {("astar", "a"): 200, ("astar", "b"): 100}, costs={"b": 11})
    report = compare.compare(base, cand)
    assert "| astar | 2 | +41.4% | 0 | 1 | 1 |" in report
    assert "| canonical | 2 | +41.4% | 0 | 1 | 1 |" in report
    assert "| canonical | b | ok, cost 10 | ok, cost 11 |" in report


class FakeClickHouse:
    def __init__(self):
        self.rows = {}

    def insert(self, table, rows, token):
        self.rows.setdefault(table, []).extend(rows)


def nightly(tmp_path, monkeypatch, commits):
    """A Nightly whose checkout resolves to commits and whose runs are faked."""
    revision = lambda c: checkout.Revision(c, datetime(2026, 1, 1, tzinfo=timezone.utc), False)
    monkeypatch.setattr(checkout, "prepare", lambda *a, **k: checkout.Checkout(
        tmp_path, tmp_path, revision(commits["tooling"]), revision(commits["plugin"])))
    monkeypatch.setattr(machine, "wait_quiet", lambda *a, **k: None)

    def fake_run(s, c, gradle, out, runner, trigger, label, log):
        directory = write_run(Path(out) / f"run-{len(list(Path(out).iterdir()))}", {("astar", "a"): 1})
        record = json.loads((directory / "run.json").read_text())
        record["executions"] = [{"backend": "astar", "status": "ok"}]
        (directory / "run.json").write_text(json.dumps(record))
        return directory
    monkeypatch.setattr(run, "run", fake_run)
    args = cli.argparse.Namespace(state=tmp_path / "state", runner="test", suite="smoke", quiet_cores=1,
                                  quiet_minutes=1, quiet_deadline=1, refresh_days=7, keep=30,
                                  clickhouse="http://unused", user="u", password_file=None)
    args.state.mkdir(exist_ok=True)
    job = cli.Nightly(args)
    job.client = FakeClickHouse()
    return job


def test_nightly_skips_when_nothing_changed(tmp_path, monkeypatch):
    commits = {"tooling": "t1", "plugin": "p1"}
    first = nightly(tmp_path, monkeypatch, commits)
    assert first() == 0
    assert [e["event"] for e in first.client.rows["runner_events"]] == ["started", "finished"]
    assert len(first.client.rows["runs"]) == 1

    again = nightly(tmp_path, monkeypatch, commits)
    assert again() == 0
    assert [e["event"] for e in again.client.rows["runner_events"]] == ["skipped"]
    assert "nothing changed" in again.client.rows["runner_events"][0]["reason"]

    commits["plugin"] = "p2"
    changed = nightly(tmp_path, monkeypatch, commits)
    assert changed() == 0
    assert len(changed.client.rows["runs"]) == 1


def test_nightly_ingests_runs_left_from_an_earlier_night(tmp_path, monkeypatch):
    job = nightly(tmp_path, monkeypatch, {"tooling": "t1", "plugin": "p1"})
    (job.state / "results").mkdir()
    write_run(job.state / "results" / "left-over", {("astar", "a"): 1})
    job()
    assert {r["run_id"] for r in job.client.rows["runs"]} == {"left-over", "run-1"}


def test_a_failed_upload_keeps_the_run_for_later(tmp_path, monkeypatch):
    directory = write_run(tmp_path / "run", {("astar", "a"): 1})
    args = cli.argparse.Namespace(clickhouse="http://127.0.0.1:9", user="u", password_file=None)
    assert not cli.upload(args, directory)
    assert not (directory / "ingested").exists()
    fake = FakeClickHouse()
    monkeypatch.setattr(cli, "client", lambda a: fake)
    assert cli.upload(args, directory)
    assert (directory / "ingested").exists() and len(fake.rows["runs"]) == 1


def test_config_file_supplies_upload_defaults(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"clickhouse": "http://ops:8123", "user": "runner_x", "runner": "x"}))
    monkeypatch.setattr(cli, "CONFIG", path)
    p = cli.argparse.ArgumentParser()
    cli.add_upload_args(p, required=True)
    a = p.parse_args([])
    assert (a.clickhouse, a.user) == ("http://ops:8123", "runner_x")
