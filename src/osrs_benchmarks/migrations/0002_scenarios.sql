-- Observations of any tooling scenario, not just canonical routes. 0001's table (keyed by
-- canonical route) is renamed out of the way rather than dropped: no runner had uploaded to it,
-- but anything that had would be kept.
RENAME TABLE benchmarks.observations TO benchmarks.observations_0001;

-- One row per measured query: a scenario and a repetition on one backend. outcome is "ok",
-- "unexpected" (the scenario's own check failed: reachability, then exact or minimum length;
-- check_message says how) or "failed" (the query threw; total_ns is then null).
CREATE TABLE IF NOT EXISTS benchmarks.observations
(
    run_id UUID,
    started_at DateTime64(3, 'UTC'),
    runner LowCardinality(String),
    trigger LowCardinality(String),
    suite LowCardinality(String),
    plugin_commit String,
    backend LowCardinality(String),
    scenario_suite LowCardinality(String),
    scenario String,
    category LowCardinality(String),
    profile LowCardinality(String),
    repetition UInt16,
    outcome LowCardinality(String),
    check_message String,
    expected_reachable Bool,
    reachable Nullable(Bool),
    path_cost Nullable(UInt32),
    path_length Nullable(UInt32),
    total_ns Nullable(UInt64),
    termination_reason LowCardinality(String),
    failure String
)
ENGINE = MergeTree
ORDER BY (suite, backend, scenario_suite, scenario, started_at)
SETTINGS non_replicated_deduplication_window = 1000;

-- A run's trigger is "nightly" or "manual"; label is what a manual run was for (--label).
ALTER TABLE benchmarks.runs ADD COLUMN IF NOT EXISTS label String DEFAULT '' AFTER trigger;
ALTER TABLE benchmarks.executions ADD COLUMN IF NOT EXISTS trigger LowCardinality(String) DEFAULT '' AFTER runner;
