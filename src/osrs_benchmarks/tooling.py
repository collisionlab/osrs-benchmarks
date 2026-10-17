"""Building tooling and running its benchmark entry point (the benchmarkCanonical Gradle task)."""
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

OUTCOMES = {"expected": "ok", "reachability_mismatch": "unexpected_reachability",
            "harness_failure": "failed"}


class Failed(Exception):
    pass


def gradle(checkout, gradle_home, *tasks, env=None, log):
    """Run Gradle tasks in the tooling checkout, appending output to log."""
    command = ["gradle", "--no-daemon", "--console=plain", "-p", str(checkout.tooling_dir),
               f"-PshortestPathDir={checkout.plugin_dir}"]
    # The plugin compiles with a Java 11 toolchain. The Nix package says where one is, so Gradle
    # neither searches the machine nor downloads one.
    jdk11 = os.environ.get("OSRS_BENCHMARKS_JDK11")
    if jdk11:
        command += [f"-Porg.gradle.java.installations.paths={jdk11}",
                    "-Porg.gradle.java.installations.auto-detect=false",
                    "-Porg.gradle.java.installations.auto-download=false"]
    command += list(tasks)
    environment = dict(os.environ, GRADLE_USER_HOME=str(gradle_home), **(env or {}))
    with open(log, "a") as out:
        out.write(f"$ {shlex.join(command)}\n")
        out.flush()
        result = subprocess.run(command, env=environment, stdout=out, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        tail = Path(log).read_text().splitlines()[-15:]
        raise Failed(f"gradle {' '.join(tasks)} exited {result.returncode}:\n" + "\n".join(tail))


def build(checkout, gradle_home, log):
    gradle(checkout, gradle_home, "-q", "testClasses", log=log)


def execute(checkout, gradle_home, manifest, directory, run_id):
    """Run one backend's manifest. Returns (execution fields, observation rows)."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    result_path = directory / "result.json"
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")
    args = f"--manifest {manifest_path} --output {result_path}"
    start = time.monotonic()
    gradle(checkout, gradle_home, "-q", "benchmarkCanonical", f"--args={args}",
           env={"BENCHMARK_RUN_ID": run_id, "BENCHMARK_PROGRESS_FILE": str(directory / "progress.jsonl")},
           log=directory / "gradle.log")
    wall = time.monotonic() - start
    envelope = json.loads(result_path.read_text())
    rows = envelope["observations"]
    want = {(c["route_id"], c["profile"], c["repetition"]) for c in manifest["cases"]}
    got = {(r["route_id"], r["account_profile"], r["repetition"]) for r in rows}
    if want != got or len(rows) != len(want):
        raise Failed(f"result has {len(rows)} observations for {len(want)} cases "
                     f"({len(want - got)} missing, {len(got - want)} unexpected)")
    metadata = envelope["execution_metadata"]
    execution = {
        "wall_seconds": wall,
        "java_version": metadata["runtime"]["java_version"],
        "java_vm": f'{metadata["runtime"]["vm_name"]} {metadata["runtime"]["vm_version"]}',
        "routing_static_build_ms": metadata.get("routing_static_build_ms"),
    }
    observations = [{
        "route_id": r["route_id"],
        "profile": r["account_profile"],
        "repetition": r["repetition"],
        "outcome": OUTCOMES[r["correctness"]],
        "expected_reachable": r["expected_reachable"],
        "reachable": r["reachable"],
        "path_cost": r["path_cost"],
        "total_ns": r["total_ns"],
        "failure": r.get("failure_reason", ""),
    } for r in rows]
    return execution, observations
