-- 0002 renamed 0001's canonical-route observations table out of the way rather than dropping it.
-- No runner uploaded to it (cedric's first upload came after 0002 was deployed), so it is empty.
DROP TABLE IF EXISTS benchmarks.observations_0001;
