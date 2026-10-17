-- One row per benchmark run: one suite at one tooling and plugin revision on one machine. The
-- runner inserts it after the run's executions and observations, so a run row means the run is
-- complete.
CREATE TABLE IF NOT EXISTS benchmarks.runs
(
    run_id UUID,
    started_at DateTime64(3, 'UTC'),
    finished_at DateTime64(3, 'UTC'),
    runner LowCardinality(String),
    trigger LowCardinality(String),
    suite LowCardinality(String),
    suite_sha256 String,
    harness_version String,
    tooling_commit String,
    tooling_commit_time DateTime('UTC'),
    tooling_dirty Bool,
    plugin_commit String,
    plugin_commit_time DateTime('UTC'),
    plugin_dirty Bool,
    kernel LowCardinality(String),
    cpu_model LowCardinality(String),
    cpu_count UInt16,
    cpu_governor LowCardinality(String),
    cpu_boost LowCardinality(String),
    clock_source LowCardinality(String),
    memory_bytes UInt64,
    load_1m Float32,
    machine_json String
)
ENGINE = MergeTree
ORDER BY (suite, runner, started_at)
SETTINGS non_replicated_deduplication_window = 1000;

-- One row per pathfinder per run: each backend runs in its own JVM.
CREATE TABLE IF NOT EXISTS benchmarks.executions
(
    run_id UUID,
    started_at DateTime64(3, 'UTC'),
    runner LowCardinality(String),
    suite LowCardinality(String),
    backend LowCardinality(String),
    status LowCardinality(String),
    wall_seconds Float64,
    java_version LowCardinality(String),
    java_vm LowCardinality(String),
    routing_static_build_ms Nullable(UInt64),
    failure String
)
ENGINE = MergeTree
ORDER BY (suite, runner, backend, started_at)
SETTINGS non_replicated_deduplication_window = 1000;

-- One row per measured query: a route, an account profile and a repetition on one backend.
-- outcome is "ok", "unexpected_reachability" (reached a route curated as unreachable for the
-- profile, or the reverse) or "failed" (the query threw; total_ns is then null).
CREATE TABLE IF NOT EXISTS benchmarks.observations
(
    run_id UUID,
    started_at DateTime64(3, 'UTC'),
    runner LowCardinality(String),
    suite LowCardinality(String),
    plugin_commit String,
    backend LowCardinality(String),
    route_id LowCardinality(String),
    profile LowCardinality(String),
    repetition UInt16,
    outcome LowCardinality(String),
    expected_reachable Bool,
    reachable Nullable(Bool),
    path_cost Nullable(UInt32),
    total_ns Nullable(UInt64),
    failure String
)
ENGINE = MergeTree
ORDER BY (suite, backend, route_id, profile, started_at)
SETTINGS non_replicated_deduplication_window = 1000;

-- What the nightly runner did and why: started, finished, skipped (with the reason) or failed.
CREATE TABLE IF NOT EXISTS benchmarks.runner_events
(
    at DateTime64(3, 'UTC'),
    runner LowCardinality(String),
    event LowCardinality(String),
    run_id Nullable(UUID),
    reason String
)
ENGINE = MergeTree
ORDER BY (runner, at)
SETTINGS non_replicated_deduplication_window = 1000;
