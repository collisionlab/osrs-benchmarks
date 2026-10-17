# osrs-benchmarks

Benchmarks for the [Shortest Path](https://github.com/Skretzo/shortest-path) plugin's two Java
pathfinders, `legacy` and `astar`. Results go to ClickHouse on `ops` and are charted in Grafana at
https://grafana.collisionlab.world.

## What is measured

A run measures one suite at one revision of
[shortest-path-tooling](https://github.com/osrs-pathfinding/shortest-path-tooling) and one revision
of the plugin, by default the plugin commit tooling pins as its `shortest-path` submodule. Tooling
owns the measuring: its `benchmarkCanonical` Gradle task takes a list of cases (route, account
profile, repetition), runs each one through the pathfinder in one JVM and reports reachability,
path cost and time per query. Its `corpus/` holds the routes and its accounts module the canonical
accounts, so the two commits identify everything a run measured.

This repo decides what to run and records it:

| | |
|---|---|
| `src/osrs_benchmarks/suites/` | suites: route tier, account profiles, backends, repetitions, warm-up |
| `src/osrs_benchmarks/migrations/` | the ClickHouse schema (database `benchmarks`) |
| `osrs-benchmarks run` | a run you start: results stay in a local directory |
| `osrs-benchmarks compare` | two run directories side by side |
| `osrs-benchmarks nightly` | the scheduled run (below) |
| `osrs-benchmarks migrate` | applies the schema; `ops` runs it on every deploy |

The Nix package pins Gradle, the JDK the benchmarks run on (17) and the Java 11 toolchain the plugin
compiles with. A JDK change is a commit here, and every run records the harness commit, the JVM,
the kernel, the CPU governor, boost and clock source.

## Running it yourself

```sh
nix run github:collisionlab/osrs-benchmarks -- run --suite smoke
```

To compare a plugin change with the commit it is based on:

```sh
nix shell github:collisionlab/osrs-benchmarks
osrs-benchmarks run --suite standard --plugin-ref master --out results
osrs-benchmarks run --suite standard --plugin-dir ~/src/shortest-path --out results
osrs-benchmarks compare results/<baseline-run-id> results/<candidate-run-id>
```

`--plugin-dir` and `--tooling-dir` use a checkout as it is, uncommitted changes included (the run
records it as dirty); `--plugin-ref`, `--plugin-repo` and `--tooling-ref` fetch a revision instead.
Checkouts and the Gradle cache live in `~/.cache/osrs-benchmarks`.

`compare` reports, per backend, the geometric mean of the per-case time ratios (each case's median
over its repetitions), how many cases got more than 10% faster or slower, the slowest changes, and
every case whose outcome or path cost changed.

## The nightly run

`infra` exports a NixOS module, `benchmark-runner`, that runs `osrs-benchmarks nightly` from a
systemd timer at 04:00 on the benchmark machine (cedric). Each night it:

1. uploads any finished run an earlier night could not;
2. fetches tooling `master` and its pinned plugin, and stops if the suite, the harness and both
   commits are what it last measured, unless that was more than a week ago (a weekly run of
   unchanged code shows drift in the machine itself);
3. waits until fewer than one core's worth of CPU has been busy for five minutes straight, and
   gives up after two hours;
4. runs the `standard` suite with the CPU governor on `performance` (the module sets it for the run
   and restores it after);
5. inserts the run into ClickHouse, then records it as measured.

Every decision (started, finished, skipped and why, failed and why) is a row in
`benchmarks.runner_events`.

## Schema

| table | one row per |
|---|---|
| `runs` | run: revisions, suite, harness and machine |
| `executions` | backend in a run: status, JVM, wall time |
| `observations` | measured query: route, profile, repetition, outcome, path cost, `total_ns` |
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
