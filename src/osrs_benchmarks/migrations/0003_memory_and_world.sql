-- Memory and the routing world, from tooling's benchmark result (shortest-path-tooling#39; null
-- for tooling revisions before it).
ALTER TABLE benchmarks.observations
    ADD COLUMN IF NOT EXISTS allocated_bytes Nullable(UInt64) AFTER total_ns;

-- Per backend JVM: heap retained after preparing (A*: its static routing data) and after the run,
-- peak heap (sum of heap pool peaks) and resident set, GC during the measured loop, and what the
-- A* static build allocated. memory_json and world_json hold the full objects.
ALTER TABLE benchmarks.executions
    ADD COLUMN IF NOT EXISTS heap_after_prepare_bytes Nullable(UInt64),
    ADD COLUMN IF NOT EXISTS heap_after_run_bytes Nullable(UInt64),
    ADD COLUMN IF NOT EXISTS peak_heap_bytes Nullable(UInt64),
    ADD COLUMN IF NOT EXISTS peak_resident_bytes Nullable(UInt64),
    ADD COLUMN IF NOT EXISTS run_gc_count Nullable(UInt32),
    ADD COLUMN IF NOT EXISTS run_gc_ms Nullable(UInt64),
    ADD COLUMN IF NOT EXISTS static_build_allocated_bytes Nullable(UInt64),
    ADD COLUMN IF NOT EXISTS memory_json String DEFAULT '';

-- The routing world the backend searched: transports for both, the static routing data's size
-- for A* (null for legacy).
ALTER TABLE benchmarks.executions
    ADD COLUMN IF NOT EXISTS transports Nullable(UInt32),
    ADD COLUMN IF NOT EXISTS transport_origins Nullable(UInt32),
    ADD COLUMN IF NOT EXISTS search_tiles Nullable(UInt32),
    ADD COLUMN IF NOT EXISTS sites Nullable(UInt32),
    ADD COLUMN IF NOT EXISTS routing_components Nullable(UInt32),
    ADD COLUMN IF NOT EXISTS reachable_banks Nullable(UInt32),
    ADD COLUMN IF NOT EXISTS crossings Nullable(UInt32),
    ADD COLUMN IF NOT EXISTS sparse_vertices Nullable(UInt32),
    ADD COLUMN IF NOT EXISTS sparse_edges Nullable(UInt32),
    ADD COLUMN IF NOT EXISTS world_json String DEFAULT '';
