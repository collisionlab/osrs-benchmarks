# osrs-benchmarks

Benchmarks for the [Shortest Path](https://github.com/Skretzo/shortest-path) plugin's two Java
pathfinders, `legacy` and `astar`, over every scenario
[shortest-path-tooling](https://github.com/osrs-pathfinding/shortest-path-tooling) defines. Every
run is uploaded to ClickHouse on `ops` and charted in Grafana at https://grafana.collisionlab.world
(*Java pathfinders* for the nightly trend, *Compare runs* for any two runs).

## What is measured

A run measures one suite at one revision of tooling and one revision of the plugin, by default
the plugin commit tooling pins as its `shortest-path` submodule. Tooling owns the scenarios (its
canonical corpus, the clue locations and the Java suites of regressions and routes; see its
`docs/scenarios.md`) and the measuring: its `benchmark` Gradle task runs the scenarios a manifest
names, each exactly as its route CLI and dashboard run it, and reports for each query whether the
scenario's own check passed (reachability, then exact or minimum length), the path cost and length,
and the search time. The two commits identify everything a run measured.

This repo decides what to run and records it:

| | |
|---|---|
| `src/osrs_benchmarks/suites/` | suites: which tooling scenarios (by suite and tier), warm-up, backends, repetitions |
| `src/osrs_benchmarks/migrations/` | the ClickHouse schema (database `benchmarks`) |
| `osrs-benchmarks run` | a run you start; uploaded where ClickHouse is configured |
| `osrs-benchmarks upload` | uploads run directories whose upload failed |
| `osrs-benchmarks compare` | two run directories side by side, in the terminal |
| `osrs-benchmarks nightly` | the scheduled run (below) |
| `osrs-benchmarks migrate` | applies the schema; `ops` runs it on every deploy |

| suite | scenarios | time on cedric |
|---|---|---|
| `all` (nightly) | every scenario of every tooling suite, 3 repetitions after warming up on the smoke tier | about an hour |
| `standard` | the canonical standard tier (135 routes × 4 accounts), 3 repetitions | about 10 minutes |
| `smoke` | the canonical smoke tier, once | under a minute |

A suite selects scenarios with `{"suite": NAME or "*", "tier": TIER}`, so a scenario or suite added
to tooling is measured without a change here.

The Nix package pins Gradle, the JDK the benchmarks run on (17) and the Java 11 toolchain the plugin
compiles with. A JDK change is a commit here, and every run records the harness commit, the JVM,
the kernel, the CPU governor, boost and clock source.

## Running it yourself

On a machine with infra's `benchmark-runner` module (cedric, theodore), `osrs-benchmarks` is on the
`PATH` and `/etc/osrs-benchmarks/config.json` says where to upload, so a run needs no other flags:

```sh
osrs-benchmarks run --suite standard --plugin-ref <commit> --label "heuristic v2"
osrs-benchmarks run --suite standard --plugin-dir ~/src/shortest-path --label "heuristic v2, local"
```

Then pick the two runs in Grafana's *Compare runs* dashboard: the machines and settings side by
side, per-backend and per-suite summaries, result changes and every scenario's time. Hand-started
runs are recorded with `trigger = manual` and their label, and stay out of the nightly trend. They
take the same lock as the nightly run, so the two never overlap.

| option | default |
|---|---|
| `--tooling-ref REF` / `--tooling-dir PATH` | tooling `master` / a checkout as it is |
| `--plugin-ref REF` (`--plugin-repo URL`) / `--plugin-dir PATH` | tooling's submodule pin / a checkout as it is |
| `--suite` | `smoke` |
| `--label` | none |
| `--no-upload` | upload when ClickHouse is configured |
| `--out` | `./results` (a copy of every run is kept here) |

A directory is used as it is, uncommitted changes included, and the run records it as dirty.
Checkouts and the Gradle cache live in `~/.cache/osrs-benchmarks`. Elsewhere (`nix run
github:collisionlab/osrs-benchmarks -- run ...`) results stay local, and `compare` reads them:

```sh
osrs-benchmarks compare results/<baseline-run-id> results/<candidate-run-id>
```

## The nightly run

`infra`'s module runs `osrs-benchmarks nightly` from a systemd timer at 04:00 on cedric. Each night
it:

1. uploads any finished run an earlier night could not;
2. fetches tooling `master` and its pinned plugin, and stops if the suite, the harness and both
   commits are what it last measured, unless that was more than a week ago (a weekly run of
   unchanged code shows drift in the machine itself);
3. waits until fewer than one core's worth of CPU has been busy for five minutes straight, and
   gives up after two hours;
4. runs the `all` suite with the CPU governor on `performance` (the module sets it for the run and
   restores it after);
5. uploads the run, then records it as measured.

Every decision (started, finished, skipped and why, failed and why) is a row in
`benchmarks.runner_events`.

## Schema

| table | one row per |
|---|---|
| `runs` | run: revisions, suite, trigger and label, harness and machine |
| `executions` | backend in a run: status, JVM, wall time; memory (heap retained after preparing and after the run, peak heap and resident set, GC, what the A* static build allocated); the routing world (transports, and for A* search tiles, sites, routing components, crossings, sparse graph) |
| `observations` | measured query: scenario suite, scenario, category, profile, repetition, outcome, path cost and length, `total_ns`, bytes allocated |
| `runner_events` | thing the nightly runner did |

A run's rows are inserted executions first and the `runs` row last, so a `runs` row means the run
is complete. Every insert carries a deduplication token, so uploading a run twice stores it once.

A schema change is a new numbered file in `migrations/`. Pushing to `main` opens a PR in `infra`
moving its `osrs-benchmarks` input, and the deploy that follows applies it.

## Development

```sh
nix develop -c pytest
nix flake check
```
