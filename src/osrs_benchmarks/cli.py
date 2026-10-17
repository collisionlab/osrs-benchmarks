"""osrs-benchmarks: run, compare and record benchmarks of the Shortest Path Java pathfinders."""
import argparse
import fcntl
import json
import os
import shutil
import socket
import sys
from pathlib import Path

from . import checkout as checkouts, clickhouse, compare, machine, run as runs, suite as suites, tooling
from ._version import VERSION


def log(message):
    print(message, flush=True)


def default_work():
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "osrs-benchmarks"


def add_revision_args(p):
    p.add_argument("--tooling-ref", help="tooling branch, tag or commit to fetch (default master)")
    p.add_argument("--tooling-dir", type=Path, help="use this tooling checkout as it is instead")
    p.add_argument("--plugin-ref", help="plugin branch, tag or commit (default: tooling's submodule pin)")
    p.add_argument("--plugin-repo", default=checkouts.PLUGIN_REPO, help="where to fetch --plugin-ref from")
    p.add_argument("--plugin-dir", type=Path, help="use this plugin checkout as it is instead")


def cmd_run(a):
    work = a.work or default_work()
    suite = suites.load(a.suite)
    checkout = checkouts.prepare(work / "checkouts", a.tooling_ref, a.tooling_dir, a.plugin_ref,
                                 a.plugin_repo, a.plugin_dir)
    directory = runs.run(suite, checkout, work / "gradle", a.out, a.runner, "manual", log)
    log(f"results: {directory}")


def cmd_compare(a):
    sys.stdout.write(compare.compare(a.baseline, a.candidate, a.top))


def client(a):
    password = Path(a.password_file).read_text().strip() if a.password_file else ""
    return clickhouse.ClickHouse(a.clickhouse, a.user, password)


def cmd_migrate(a):
    clickhouse.migrate(client(a), log)


class Nightly:
    """The scheduled run: measure tooling master (with its pinned plugin) when anything changed."""

    def __init__(self, a):
        self.a = a
        self.state = a.state
        self.results = self.state / "results"
        self.client = client(a)

    def event(self, event, reason="", run_id=None):
        log(f"{event}: {reason}" if reason else event)
        row = {"at": runs.timestamp(runs.now()), "runner": self.a.runner, "event": event,
               "run_id": run_id, "reason": reason}
        try:
            self.client.insert("runner_events", [row], f"{self.a.runner}-{row['at']}-{event}")
        except (OSError, RuntimeError) as e:
            log(f"could not record the {event} event: {e}")

    def ingest_pending(self):
        """Ingest runs an earlier night finished but could not upload."""
        for directory in sorted(self.results.glob("*/run.json")):
            directory = directory.parent
            if not (directory / "ingested").exists():
                log(f"ingesting {directory.name} from an earlier run")
                runs.ingest(self.client, directory)
                (directory / "ingested").touch()

    def prune(self, keep):
        done = sorted((d for d in self.results.glob("*") if (d / "ingested").exists()),
                      key=lambda d: d.stat().st_mtime)
        for directory in done[:-keep]:
            shutil.rmtree(directory)

    def __call__(self):
        a = self.a
        self.results.mkdir(parents=True, exist_ok=True)
        lock = open(self.state / "lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.event("skipped", "another run holds the lock")
            return 0
        self.ingest_pending()

        suite = suites.load(a.suite)
        checkout = checkouts.prepare(self.state / "checkouts", tooling_ref="master")
        key = {"suite": suite.name, "suite_sha256": suite.sha256, "harness": VERSION,
               "tooling": checkout.tooling.commit, "plugin": checkout.plugin.commit}
        last_path = self.state / "last.json"
        last = json.loads(last_path.read_text()) if last_path.exists() else {}
        if last.get("key") == key:
            age_days = (runs.now().timestamp() - last["at"]) / 86400
            if age_days < a.refresh_days:
                self.event("skipped", f"nothing changed since run {last['run_id']}")
                return 0
            log(f"nothing changed, but the last run is {age_days:.0f} days old: measuring again")

        try:
            machine.wait_quiet(a.quiet_cores, a.quiet_minutes, a.quiet_deadline, log=log)
        except machine.Busy as e:
            self.event("skipped", str(e))
            return 0

        self.event("started", f"tooling {checkout.tooling.commit[:12]}, plugin {checkout.plugin.commit[:12]}")
        try:
            directory = runs.run(suite, checkout, self.state / "gradle", self.results, a.runner, "nightly", log)
        except (tooling.Failed, OSError) as e:
            self.event("failed", str(e))
            return 1
        run_id = directory.name
        runs.ingest(self.client, directory)
        (directory / "ingested").touch()
        last_path.write_text(json.dumps({"key": key, "run_id": run_id, "at": runs.now().timestamp()}) + "\n")
        _, executions, _ = runs.load(directory)
        failed = [e["backend"] for e in executions if e["status"] != "ok"]
        if failed:
            self.event("failed", f"{', '.join(failed)} did not complete", run_id)
        else:
            self.event("finished", "", run_id)
        self.prune(a.keep)
        return 1 if failed else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="osrs-benchmarks", description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run a suite and keep the results locally")
    r.add_argument("--suite", default="smoke", help=f"one of {', '.join(suites.names())}, or a file")
    add_revision_args(r)
    r.add_argument("--out", type=Path, default=Path("results"), help="where run directories go")
    r.add_argument("--work", type=Path, help="checkouts and Gradle cache (default ~/.cache/osrs-benchmarks)")
    r.add_argument("--runner", default=socket.gethostname())
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("compare", help="compare two run directories")
    c.add_argument("baseline", type=Path)
    c.add_argument("candidate", type=Path)
    c.add_argument("--top", type=int, default=10)
    c.set_defaults(func=cmd_compare)

    for name, helptext in (("migrate", "apply the ClickHouse schema"),
                           ("nightly", "the scheduled run: measure master and record it")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--clickhouse", required=True, help="ClickHouse HTTP URL")
        s.add_argument("--user", default="default")
        s.add_argument("--password-file")
        if name == "migrate":
            s.set_defaults(func=cmd_migrate)
    n = sub.choices["nightly"]
    n.add_argument("--state", type=Path, required=True)
    n.add_argument("--runner", default=socket.gethostname())
    n.add_argument("--suite", default="standard")
    n.add_argument("--quiet-cores", type=float, default=1.0,
                   help="start only once fewer cores than this were busy ...")
    n.add_argument("--quiet-minutes", type=int, default=5, help="... for this many minutes straight")
    n.add_argument("--quiet-deadline", type=int, default=120, help="give up after this many minutes")
    n.add_argument("--refresh-days", type=float, default=7,
                   help="measure again after this long even if nothing changed")
    n.add_argument("--keep", type=int, default=30, help="local run directories to keep")
    n.set_defaults(func=lambda a: Nightly(a)())

    a = p.parse_args(argv)
    sys.exit(a.func(a) or 0)
