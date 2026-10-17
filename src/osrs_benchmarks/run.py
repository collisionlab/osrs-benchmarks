"""One benchmark run: build, run each backend, and write the run directory.

A run directory holds run.json (the run row and one execution row per backend, as inserted into
ClickHouse), observations.jsonl (the observation rows) and a directory per backend with the
manifest, tooling's raw result and the Gradle log.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import machine, suite as suites, tooling
from ._version import VERSION


def timestamp(moment, millis=True):
    text = moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    return text[:-3] if millis else text[:-7]


def now():
    return datetime.now(timezone.utc)


def run(suite, checkout, gradle_home, out_dir, runner, trigger, log=print):
    """Run suite on checkout. Returns the run directory; raises tooling.Failed if it can't build."""
    run_id = str(uuid.uuid4())
    started = now()
    directory = Path(out_dir) / run_id
    directory.mkdir(parents=True)
    described = machine.describe()
    log(f"run {run_id}: suite {suite.name}, tooling {checkout.tooling.commit[:12]}, "
        f"plugin {checkout.plugin.commit[:12]}")
    log("building")
    tooling.build(checkout, gradle_home, directory / "build.log")

    logical = suites.cases(suite, checkout.tooling_dir)
    common = {"run_id": run_id, "started_at": timestamp(started), "runner": runner,
              "suite": suite.name}
    executions, observations = [], []
    for backend in suite.backends:
        log(f"running {backend}: {len(logical)} cases x {suite.repetitions}")
        execution = dict(common, backend=backend, status="ok", wall_seconds=0.0, java_version="",
                         java_vm="", routing_static_build_ms=None, failure="")
        try:
            fields, rows = tooling.execute(checkout, gradle_home, suites.manifest(suite, backend, logical),
                                           directory / backend, run_id)
            execution.update(fields)
            observations += [dict(common, plugin_commit=checkout.plugin.commit, backend=backend, **row)
                             for row in rows]
        except (tooling.Failed, OSError, KeyError, ValueError) as e:
            execution.update(status="failed", failure=str(e))
            log(f"{backend} failed: {e}")
        executions.append(execution)

    run_row = dict(
        common,
        finished_at=timestamp(now()),
        trigger=trigger,
        suite_sha256=suite.sha256,
        harness_version=VERSION,
        tooling_commit=checkout.tooling.commit,
        tooling_commit_time=timestamp(checkout.tooling.commit_time, millis=False),
        tooling_dirty=checkout.tooling.dirty,
        plugin_commit=checkout.plugin.commit,
        plugin_commit_time=timestamp(checkout.plugin.commit_time, millis=False),
        plugin_dirty=checkout.plugin.dirty,
        **{k: described[k] for k in ("kernel", "cpu_model", "cpu_count", "cpu_governor", "cpu_boost",
                                    "clock_source", "memory_bytes", "load_1m")},
        machine_json=json.dumps({"hostname": described["hostname"], **described["extra"]}, sort_keys=True),
    )
    with open(directory / "observations.jsonl", "w") as out:
        for row in observations:
            out.write(json.dumps(row) + "\n")
    # Written last: a run directory with run.json is complete.
    (directory / "run.json").write_text(json.dumps({"run": run_row, "executions": executions}, indent=1) + "\n")
    return directory


def load(directory):
    """(run row, execution rows, observation rows) of a run directory."""
    directory = Path(directory)
    record = json.loads((directory / "run.json").read_text())
    with open(directory / "observations.jsonl") as rows:
        observations = [json.loads(line) for line in rows]
    return record["run"], record["executions"], observations


def ingest(client, directory):
    """Insert a run directory. Safe to repeat: every insert carries a deduplication token."""
    run_row, executions, observations = load(directory)
    run_id = run_row["run_id"]
    client.insert("executions", executions, f"{run_id}-executions")
    for start in range(0, len(observations), 50000):
        client.insert("observations", observations[start:start + 50000], f"{run_id}-observations-{start}")
    client.insert("runs", [run_row], f"{run_id}-run")
