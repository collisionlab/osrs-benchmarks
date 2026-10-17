"""Building tooling, reading its scenario index and running its benchmark Gradle task."""
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

OUTCOMES = {"ok", "unexpected", "failed"}
# Typed columns copied from the result's memory and world objects (tooling#39 on); absent
# fields are null. The whole objects are kept as memory_json and world_json.
MEMORY_FIELDS = ("heap_after_prepare_bytes", "heap_after_run_bytes", "peak_heap_bytes", "peak_resident_bytes",
                 "run_gc_count", "run_gc_ms", "static_build_allocated_bytes")
WORLD_FIELDS = ("transports", "transport_origins", "search_tiles", "sites", "routing_components",
                "reachable_banks", "crossings", "sparse_vertices", "sparse_edges")


class Failed(Exception):
    pass


def gradle(checkout, gradle_home, *tasks, env=None, log, stdout=None):
    """Run Gradle tasks in the tooling checkout, appending output to log (and stdout to stdout)."""
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
        result = subprocess.run(command, env=environment, stdout=stdout or out, stderr=out)
    if result.returncode != 0:
        tail = Path(log).read_text().splitlines()[-15:]
        raise Failed(f"gradle {' '.join(tasks)} exited {result.returncode}:\n" + "\n".join(tail))


def build(checkout, gradle_home, log):
    gradle(checkout, gradle_home, "-q", "testClasses", log=log)


def scenario_index(checkout, gradle_home, log):
    """{suite: [{name, category, profile, tiers, description}]}: every scenario tooling has."""
    path = Path(log).with_name("scenario-index.json")
    with open(path, "w") as out:
        gradle(checkout, gradle_home, "-q", "scenarioIndex", log=log, stdout=out)
    lines = [line for line in path.read_text().splitlines() if line.startswith("{")]
    if not lines:
        raise Failed("scenarioIndex printed no index")
    return json.loads(lines[-1])


def execute(checkout, gradle_home, manifest, directory, run_id):
    """Run one backend's manifest. Returns (execution fields, observation rows)."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    result_path = directory / "result.json"
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")
    args = f"--manifest {manifest_path} --output {result_path}"
    start = time.monotonic()
    gradle(checkout, gradle_home, "-q", "benchmark", f"--args={args}",
           env={"BENCHMARK_RUN_ID": run_id, "BENCHMARK_PROGRESS_FILE": str(directory / "progress.jsonl")},
           log=directory / "gradle.log")
    wall = time.monotonic() - start
    envelope = json.loads(result_path.read_text())
    if envelope.get("format_version") != 2:
        raise Failed(f"tooling wrote a format {envelope.get('format_version')} result; this harness reads format 2")
    rows = envelope["observations"]
    want = {(c["suite"], c["scenario"], c["repetition"]) for c in manifest["cases"]}
    got = {(r["suite"], r["scenario"], r["repetition"]) for r in rows}
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
    memory, world = metadata.get("memory", {}), metadata.get("world", {})
    execution.update({f: memory.get(f) for f in MEMORY_FIELDS})
    execution.update({f: world.get(f) for f in WORLD_FIELDS})
    execution["memory_json"] = json.dumps(memory, sort_keys=True) if memory else ""
    execution["world_json"] = json.dumps(world, sort_keys=True) if world else ""
    fields = ("scenario", "category", "profile", "repetition", "outcome", "expected_reachable",
              "reachable", "path_cost", "path_length", "total_ns", "termination_reason", "failure")
    observations = []
    for r in rows:
        if r["outcome"] not in OUTCOMES:
            raise Failed(f"unknown outcome {r['outcome']!r}")
        # "suite" here is the scenario's tooling suite; a run's suite is the benchmark suite.
        observations.append({"scenario_suite": r["suite"], "check_message": r["check"],
                             "allocated_bytes": r.get("allocated_bytes"), **{f: r[f] for f in fields}})
    return execution, observations
